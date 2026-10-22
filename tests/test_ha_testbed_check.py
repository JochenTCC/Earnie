"""HA Testbed P4: ``scripts.ha_testbed_check`` against a simulated bench (no HA / Earnie)."""
from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from ehal.push_signals import HEARTBEAT_ID, HUB_WRITE_FAILED_ID
from ehal.qualified_ids import field_kind
from house_sim.archetype_gen import generate_archetype, write_archetype
from integrations.ha_carrier_yaml import _sanitize_id
from scripts import ha_testbed_check as chk
from test_house_sim_archetype_gen import _full_pack

REPEAT_S = 10.0
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
SETPOINT = "ess.house.set_ess_charge_power_limit"


class World:
    """Fake clock + HA + Earnie: pushes arrive every tick, writes propagate with delays."""

    def __init__(self, archetype: chk.Archetype, *, apply_ha: bool = True, report_failures: bool = True):
        self.arch = archetype
        self.t = 0.0
        self.apply_ha = apply_ha
        self.report_failures = report_failures
        self.reject = False
        self.status: dict[str, float] = {"heartbeat_earnie": 1}
        self.published: dict[str, float] = {}
        self.publish_log: list[tuple[str, float]] = []
        self.pending: list[tuple[float, str, float]] = []  # (due, kind, value) kind: status|ha
        self.silent: set[str] = set()  # ehal ids that do not push
        self.unavailable_until: dict[str, float] = {}
        self.automations_off: set[str] = set()
        self.services: list[tuple[str, str, dict]] = []
        self.failing = False
        self.overwrite: tuple[float, float] | None = None  # (time, value): Earnie writes its own setpoint
        self.states: dict[str, dict] = {}
        for ehal_id, entity_id in archetype.placeholders.items():
            unit = archetype.units[entity_id]
            attrs = {"unit_of_measurement": unit} if unit else {}
            if field_kind(ehal_id).startswith("set_"):
                attrs.update({"min": -100000, "max": 100000})
            self.states[entity_id] = {"entity_id": entity_id, "state": "5000" if ehal_id == SETPOINT else "100", "attributes": attrs}
        self.rows: dict[str, dict] = {}
        for ehal_id in archetype.reads() + [HEARTBEAT_ID]:
            self.rows[ehal_id] = {"value": 1.0, "parse_ok": True}
        self.stamp: dict[str, float] = {k: 0.0 for k in self.rows}
        for ehal_id in archetype.reads():
            self.states[archetype.placeholders[ehal_id]]["state"] = "100"
        self.automations = {
            f"automation.push_{i}": {"entity_id": f"automation.push_{i}", "state": "on", "attributes": {"id": f"earnie_push_{_sanitize_id(eid)}"}}
            for i, eid in enumerate(archetype.reads())
        }

    # clock
    def now(self):
        return BASE + timedelta(seconds=self.t)

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        self._tick()

    def _automation_of(self, ehal_id):
        wanted = f"earnie_push_{_sanitize_id(ehal_id)}"
        return next(a["entity_id"] for a in self.automations.values() if a["attributes"]["id"] == wanted)

    def _tick(self):
        if self.overwrite and self.t >= self.overwrite[0]:
            self.status[SETPOINT] = self.overwrite[1]
            self.pending.clear()
            self.overwrite = None
        for due, kind, value in [p for p in self.pending if p[0] <= self.t]:
            self.pending.remove((due, kind, value))
            if kind == "status":
                self.status[SETPOINT] = value
            elif self.reject:
                self.failing = True
            elif self.apply_ha:
                self.states[self.arch.placeholders[SETPOINT]]["state"] = str(value)
        for ehal_id in list(self.rows):
            entity = self.arch.placeholders.get(ehal_id)
            if ehal_id in self.silent:
                continue
            if ehal_id != HEARTBEAT_ID and self._automation_of(ehal_id) in self.automations_off:
                continue
            if entity and self.unavailable_until.get(entity, -1) > self.t:
                self.states[entity]["state"] = "unavailable"
                continue
            if entity and self.states[entity]["state"] == "unavailable":
                self.states[entity]["state"] = "100"
            self.stamp[ehal_id] = self.t
        if self.failing and self.report_failures:
            self.rows.setdefault(HUB_WRITE_FAILED_ID, {"value": 1.0, "parse_ok": True})
            self.stamp[HUB_WRITE_FAILED_ID] = self.t

    # Earnie
    def load_inbox(self):
        return {
            k: {**v, "last_ts": (BASE + timedelta(seconds=self.stamp[k])).isoformat()}
            for k, v in self.rows.items()
        }

    def fetch_status(self):
        return dict(self.status)

    def publish(self, qid, value):
        self.publish_log.append((qid, value))
        self.published[qid] = value
        self.pending.append((self.t + 3, "status", value))
        self.pending.append((self.t + 9, "ha", value))

    # HA
    def get_state(self, entity_id):
        return self.states.get(entity_id)

    def list_states(self):
        return list(self.states.values()) + list(self.automations.values())

    def ping(self):
        return None

    def call_service(self, domain, service, data):
        self.services.append((domain, service, data))
        if (domain, service) == ("earnie_house_sim", "reject_writes"):
            self.reject = bool(data["enabled"])
            if not self.reject:
                self.failing = False
                self.rows.pop(HUB_WRITE_FAILED_ID, None)
                self.pending.append((self.t + 2, "ha", self.status.get(SETPOINT, 0.0)))
        elif (domain, service) == ("earnie_house_sim", "set_unavailable"):
            self.unavailable_until[data["entity_id"]] = self.t + data["minutes"] * 60
            self.states[data["entity_id"]]["state"] = "unavailable"
        elif domain == "automation":
            (self.automations_off.add if service == "turn_off" else self.automations_off.discard)(data["entity_id"])

    def bench(self, *, with_ha=True, timeout_s=60.0):
        return chk.Bench(
            archetype=self.arch,
            repeat_s=REPEAT_S,
            timeout_s=timeout_s,
            ha=self if with_ha else None,
            load_inbox=self.load_inbox,
            fetch_status=self.fetch_status,
            publish=self.publish,
            published_value=lambda qid: self.published.get(qid),
            sleep=self.sleep,
            monotonic=self.monotonic,
            now=self.now,
        )


@pytest.fixture
def archetype(tmp_path):
    arch = generate_archetype(*_full_pack())
    write_archetype(arch, tmp_path / "earnie_pack")
    return chk.Archetype.load(tmp_path / "earnie_pack")


def _by_name(results):
    return {r.name: r for r in results}


# --- happy path --------------------------------------------------------------


def test_full_run_passes(archetype):
    world = World(archetype)
    results = chk.run_checks(world.bench())
    assert [r for r in results if r.status != chk.PASS] == [], chk.format_table(results)
    names = " | ".join(r.name for r in results)
    for part in ("sim entities", "reads fresh", "heartbeat", "status.json", "reject_writes", "set_unavailable", "stopped power", "stopped energy"):
        assert part in names
    assert chk.exit_code(results) == 0
    # The bench is left as found: automations on, reject off, setpoint restored.
    assert not world.automations_off and not world.reject
    assert world.publish_log[-1] == (SETPOINT, 5000.0)


def test_negative_cases_can_be_skipped(archetype):
    world = World(archetype)
    results = chk.run_checks(world.bench(), negative=False)
    assert all(r.status == chk.PASS for r in results)
    assert not any(s[0] == "earnie_house_sim" for s in world.services)


def test_without_ha_token_ha_checks_are_skipped(archetype):
    world = World(archetype)
    results = chk.run_checks(world.bench(with_ha=False))
    skipped = [r for r in results if r.status == chk.SKIP]
    assert skipped and all("--ha-token" in r.detail for r in skipped)
    assert any(r.status == chk.PASS for r in results)  # inbox checks still run
    assert chk.exit_code(results) == 0
    assert chk.exit_code(results, require_all=True) == 1


# --- failures ----------------------------------------------------------------


def test_stale_and_missing_inbox_signals_fail(archetype):
    world = World(archetype)
    reads = archetype.reads()
    world.stamp[reads[0]] = -100.0  # last push long ago
    del world.rows[reads[1]]
    del world.stamp[reads[1]]
    results = chk.check_inbox(world.bench())
    first = results[0]
    assert first.status == chk.FAIL and reads[0] in first.detail and f"missing: {reads[1]}" in first.detail


def test_silent_heartbeat_fails(archetype):
    world = World(archetype)
    world.stamp[HEARTBEAT_ID] = -100.0
    assert _by_name(chk.check_inbox(world.bench()))["heartbeat from HA"].status == chk.FAIL


def test_missing_entity_wrong_unit_and_unavailable_fail(archetype):
    world = World(archetype)
    entities = list(archetype.units)
    del world.states[entities[0]]
    wrong = next(e for e in entities if archetype.units[e] == "W" and e in world.states)
    world.states[wrong]["attributes"]["unit_of_measurement"] = "kW"
    gone = next(e for e in entities if e in world.states and e != wrong)
    world.states[gone]["state"] = "unavailable"
    (result,) = chk.check_ha_entities(world.bench())
    assert result.status == chk.FAIL
    assert f"{entities[0]}: missing" in result.detail
    assert f"{wrong}: unit 'kW'" in result.detail
    assert f"{gone}: state unavailable" in result.detail


def test_unreachable_ha_fails(archetype):
    world = World(archetype)

    def boom():
        raise OSError("connection refused")

    world.ping = boom
    (result,) = chk.check_ha_entities(world.bench())
    assert result.status == chk.FAIL and "not reachable" in result.detail


def _http_error(code: int, reason: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://ha.test/api/states/x", code, reason, {}, None)


def test_http_401_from_ha_fails_every_ha_check_instead_of_crashing(archetype):
    # Regression: a rejected token crashed the run with a traceback in the round-trip check.
    world = World(archetype)

    def unauthorized(*_args, **_kwargs):
        raise _http_error(401, "Unauthorized")

    world.ping = unauthorized
    world.get_state = unauthorized
    world.list_states = unauthorized
    world.call_service = unauthorized
    results = chk.run_checks(world.bench())
    by_name = _by_name(results)
    for name in (
        "HA reachable, sim entities exist with expected units",
        "setpoint round trip",
        "reject_writes -> hub_write_failed reported to Earnie",
        "set_unavailable -> no crash, push resumes",
        "stopped push",
    ):
        assert by_name[name].status == chk.FAIL, name
        assert "401" in by_name[name].detail and "HA_TESTBED_TOKEN" in by_name[name].detail
    assert by_name["heartbeat from HA"].status == chk.PASS  # inbox checks do not need HA
    assert chk.exit_code(results) == 1


def test_non_auth_http_error_is_reported_without_token_hint(archetype):
    world = World(archetype)

    def broken(*_args, **_kwargs):
        raise _http_error(500, "Internal Server Error")

    world.get_state = broken
    result = _by_name(chk.run_checks(world.bench(), negative=False))["setpoint round trip"]
    assert result.status == chk.FAIL
    assert "HTTP 500" in result.detail and "http://ha.test/api/states/x" in result.detail
    assert "HA_TESTBED_TOKEN" not in result.detail


def test_roundtrip_fails_when_ha_never_applies_and_still_restores(archetype):
    world = World(archetype, apply_ha=False)
    results = _by_name(chk.check_setpoint_roundtrip(world.bench(timeout_s=30)))
    assert results["ess.house.set_ess_charge_power_limit published -> status.json"].status == chk.PASS
    ha_result = next(r for n, r in results.items() if n.startswith("status.json ->"))
    assert ha_result.status == chk.FAIL
    assert world.publish_log[-1] == (SETPOINT, 5000.0)


def test_roundtrip_names_an_optimizer_overwrite_of_the_setpoint(archetype):
    # Regression (bench L8): the first optimizer cycle after an Earnie start rewrote the
    # ESS limit while the check waited for HA; the failure said only "did not reach".
    world = World(archetype)
    world.overwrite = (5.0, 4321.0)  # after status.json showed the value (t+3), before HA applied it (t+9)
    results = _by_name(chk.check_setpoint_roundtrip(world.bench(timeout_s=30)))
    ha_result = next(r for n, r in results.items() if n.startswith("status.json ->"))
    assert ha_result.status == chk.FAIL
    assert "status.json now shows 4321" in ha_result.detail and "optimizer cycle" in ha_result.detail


def test_failure_without_an_overwrite_does_not_blame_the_optimizer(archetype):
    world = World(archetype, apply_ha=False)
    results = _by_name(chk.check_setpoint_roundtrip(world.bench(timeout_s=30)))
    ha_result = next(r for n, r in results.items() if n.startswith("status.json ->"))
    assert ha_result.status == chk.FAIL and "optimizer" not in ha_result.detail


def test_roundtrip_fails_when_status_never_shows_the_value(archetype):
    world = World(archetype)
    world.pending.clear()
    world.publish = lambda qid, value: world.publish_log.append((qid, value))
    results = chk.check_setpoint_roundtrip(world.bench(timeout_s=20))
    assert results[0].status == chk.FAIL and results[1].status == chk.SKIP


def test_roundtrip_uses_the_published_ledger_value_for_restore(archetype):
    world = World(archetype)
    world.published[SETPOINT] = 4200.0
    chk.check_setpoint_roundtrip(world.bench())
    assert world.publish_log[-1] == (SETPOINT, 4200.0)


def test_reject_writes_fails_without_hub_write_failed(archetype):
    world = World(archetype, report_failures=False)
    results = chk.check_reject_writes(world.bench())
    assert results[0].status == chk.FAIL and HUB_WRITE_FAILED_ID in results[0].detail
    assert world.reject is False  # always switched off again


def test_set_unavailable_fails_when_the_link_dies(archetype):
    world = World(archetype)
    world.silent.add(HEARTBEAT_ID)
    world.stamp[HEARTBEAT_ID] = -100.0
    (result,) = chk.check_set_unavailable(world.bench())
    assert result.status == chk.FAIL and "heartbeat" in result.detail


def test_stopped_push_fails_when_power_stays_ok(archetype):
    world = World(archetype)
    # Automations "off" but the signal keeps arriving (stale detection broken).
    world._automation_of = lambda ehal_id: "automation.never"
    results = _by_name(chk.check_stopped_push(world.bench()))
    assert results["stopped power push -> 0 angenommen (verstummt)"].status == chk.FAIL


def test_stopped_push_skips_when_last_value_was_zero(archetype):
    world = World(archetype)
    power_id = next(
        i
        for i in archetype.reads()
        if field_kind(i).startswith("sens_") and "power" in field_kind(i) and "energy" not in field_kind(i)
    )
    world.rows[power_id]["value"] = 0.0
    results = _by_name(chk.check_stopped_push(world.bench()))
    assert results["stopped power push -> 0 angenommen (verstummt)"].status == chk.SKIP
    assert not world.automations_off  # re-enabled


def test_stopped_push_without_push_automation_in_ha_fails(archetype):
    world = World(archetype)
    world.automations.clear()
    results = chk.check_stopped_push(world.bench())
    assert results[0].status == chk.FAIL and "no push automation" in results[0].detail


def test_roundtrip_skips_when_no_safe_setpoint(archetype):
    world = World(archetype)
    bench = world.bench()
    bench.archetype = chk.Archetype(
        {k: v for k, v in archetype.placeholders.items() if not field_kind(k).startswith("set_")},
        archetype.units,
        archetype.meta,
    )
    (result,) = chk.check_setpoint_roundtrip(bench)
    assert result.status == chk.SKIP and "no ESS limit" in result.detail


# --- reporting / CLI ---------------------------------------------------------


def test_format_table_and_exit_codes():
    results = [chk.Result("a", chk.PASS), chk.Result("b", chk.FAIL, "why"), chk.Result("c", chk.SKIP, "n/a")]
    table = chk.format_table(results)
    assert "FAIL  b" in table and "why" in table and "1 passed, 1 failed, 1 skipped" in table
    assert chk.exit_code(results) == 1
    assert chk.exit_code([results[0], results[2]]) == 0
    assert chk.exit_code([results[0], results[2]], require_all=True) == 1


def test_pack_unchanged_check(tmp_path, archetype):
    house, components = _full_pack()
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "house_profiles.json").write_text(json.dumps(house), encoding="utf-8")
    (cfg / "components.json").write_text(json.dumps(components), encoding="utf-8")
    assert chk.check_pack_unchanged(archetype, cfg).status == chk.PASS
    components["batteries"][0]["battery_capacity_kwh"] = 99.0
    (cfg / "components.json").write_text(json.dumps(components), encoding="utf-8")
    assert chk.check_pack_unchanged(archetype, cfg).status == chk.FAIL


def test_main_reports_missing_archetype(tmp_path, capsys):
    assert chk.main(["--testbed-dir", str(tmp_path)]) == 2
    assert "cannot load the generated archetype" in capsys.readouterr().err


def test_archetype_load_splits_reads_and_writes(archetype):
    assert all(not field_kind(i).startswith("set_") for i in archetype.reads())
    assert SETPOINT in archetype.writes()
