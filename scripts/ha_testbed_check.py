"""Automated check of a running HA contract testbed (HA Testbed P4).

  python -m scripts.ha_testbed_check --ha-token <long-lived token> [--config-dir <cfg>]

Needs the bench from P1–P3 running (generated archetype installed and configured
in HA, carrier package loaded, Earnie listening on :8541). Checks:

1. HA reachable, every generated entity exists with the expected unit.
2. Every activated read signal (and the heartbeat) is fresh in the Earnie push inbox.
3. Setpoint round trip: publish in Earnie -> ``status.json`` -> sim ``number`` in HA.
4. Negative cases: ``reject_writes`` -> ``hub_write_failed``; ``set_unavailable`` -> no
   crash and recovery; stopped push -> ``0 angenommen (verstummt)`` for power while an
   energy counter is never invented as 0.

Checks that need HA are reported as SKIP without ``--ha-token``. Exit code 1 on any
FAIL (also on SKIP with ``--require-all``). The round-trip and negative cases change
setpoints / switch automations / inject faults and restore them afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ehal.push_signals import HEARTBEAT_ID, HUB_WRITE_FAILED_ID
from ehal.qualified_ids import field_kind
from house_sim.archetype_gen import pack_sha256
from integrations.ha_carrier_yaml import _sanitize_id
from integrations.ha_units import UnitMismatchError, field_quantity, from_ehal, to_ehal
from runtime_store.ehal_push_inbox import (
    STATE_ZERO_ASSUMED_NEVER,
    STATE_ZERO_ASSUMED_SILENT,
    STATE_ZERO_HELD,
    STATE_ZERO_HELD_NO_LINK,
    derive_state,
    expected_repeat_s,
    link_alive,
)
from scripts.ha_testbed import DEFAULT_TESTBED_DIR, ha_dir
from scripts.ha_testbed_build import ARCHETYPES_RELPATH, DEFAULT_ARCHETYPE_NAME

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
# The inbox file is flushed at most once per second; add slack for it and clock jitter.
FLUSH_SLACK_S = 2.0
POLL_S = 1.0
SIM_DOMAIN = "earnie_house_sim"
_ZERO_STATES = frozenset(
    {STATE_ZERO_HELD, STATE_ZERO_HELD_NO_LINK, STATE_ZERO_ASSUMED_SILENT, STATE_ZERO_ASSUMED_NEVER}
)
_SETPOINT_PREFERENCE = (
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_evcs_max_current",
)
_DELTA = {"power": 500.0, "current": 1.0}


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str = ""


class HaApi:
    """Minimal HA REST client (long-lived token)."""

    def __init__(self, base_url: str, token: str, *, timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_s

    def _request(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
            raw = resp.read()
        return json.loads(raw) if raw else None

    def ping(self) -> None:
        self._request("GET", "/api/")

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        try:
            return self._request("GET", f"/api/states/{entity_id}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def list_states(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/states")

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        self._request("POST", f"/api/services/{domain}/{service}", data)


@dataclass
class Archetype:
    placeholders: dict[str, str]  # ehal_id -> entity_id
    units: dict[str, str]  # entity_id -> expected unit ("" = none)
    meta: dict[str, Any]

    @classmethod
    def load(cls, directory: Path) -> "Archetype":
        entities = json.loads((directory / "entities.json").read_text(encoding="utf-8"))["entities"]
        return cls(
            placeholders=json.loads((directory / "placeholders.json").read_text(encoding="utf-8")),
            units={
                e["entity_id"]: str((e.get("attributes") or {}).get("unit_of_measurement") or "")
                for e in entities
            },
            meta=json.loads((directory / "meta.json").read_text(encoding="utf-8")),
        )

    def reads(self) -> list[str]:
        return [i for i in self.placeholders if not field_kind(i).startswith("set_")]

    def writes(self) -> list[str]:
        return [i for i in self.placeholders if field_kind(i).startswith("set_")]


@dataclass
class Bench:
    archetype: Archetype
    repeat_s: float
    timeout_s: float
    ha: HaApi | None
    load_inbox: Callable[[], dict[str, dict[str, Any]]]
    fetch_status: Callable[[], dict[str, Any]]
    publish: Callable[[str, float], None]
    published_value: Callable[[str], float | None]
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    log: Callable[[str], None] = field(default=lambda msg: None)

    def wait_until(self, predicate: Callable[[], bool], timeout_s: float | None = None) -> bool:
        deadline = self.monotonic() + (self.timeout_s if timeout_s is None else timeout_s)
        while True:
            if predicate():
                return True
            if self.monotonic() >= deadline:
                return False
            self.sleep(POLL_S)

    @property
    def fresh_limit_s(self) -> float:
        return 2 * self.repeat_s + FLUSH_SLACK_S


def _age_s(row: dict[str, Any] | None, now: datetime) -> float | None:
    stamp = (row or {}).get("last_ts")
    if not stamp:
        return None
    return (now - datetime.fromisoformat(str(stamp))).total_seconds()


def _need_ha(bench: Bench, name: str) -> Result | None:
    if bench.ha is None:
        return Result(name, SKIP, "needs --ha-token")
    return None


# --- 1. HA entities ----------------------------------------------------------


def check_ha_entities(bench: Bench) -> list[Result]:
    name = "HA reachable, sim entities exist with expected units"
    if (skip := _need_ha(bench, name)) is not None:
        return [skip]
    try:
        bench.ha.ping()
    except (OSError, urllib.error.URLError) as exc:
        return [Result(name, FAIL, f"HA not reachable: {exc}")]
    problems: list[str] = []
    for entity_id, unit in bench.archetype.units.items():
        state = bench.ha.get_state(entity_id)
        if state is None:
            problems.append(f"{entity_id}: missing")
            continue
        if str(state.get("state")) in ("unavailable", "unknown"):
            problems.append(f"{entity_id}: state {state.get('state')}")
        actual = str((state.get("attributes") or {}).get("unit_of_measurement") or "")
        if actual != unit:
            problems.append(f"{entity_id}: unit {actual!r}, expected {unit!r}")
    count = len(bench.archetype.units)
    if problems:
        return [Result(name, FAIL, "; ".join(problems))]
    return [Result(name, PASS, f"{count} entities")]


# --- 2. Earnie inbox ---------------------------------------------------------


def check_inbox(bench: Bench) -> list[Result]:
    rows = bench.load_inbox()
    now = bench.now()
    limit = bench.fresh_limit_s
    missing, stale = [], []
    for ehal_id in bench.archetype.reads():
        age = _age_s(rows.get(ehal_id), now)
        if age is None:
            missing.append(ehal_id)
        elif age > limit:
            stale.append(f"{ehal_id} ({age:.0f}s)")
    results = []
    name = f"all {len(bench.archetype.reads())} activated reads fresh in the inbox (< {limit:g}s)"
    if missing or stale:
        detail = "; ".join(
            ([f"missing: {', '.join(missing)}"] if missing else [])
            + ([f"stale: {', '.join(stale)}"] if stale else [])
        )
        results.append(Result(name, FAIL, detail))
    else:
        results.append(Result(name, PASS))
    age = _age_s(rows.get(HEARTBEAT_ID), now)
    if age is None:
        results.append(Result("heartbeat from HA", FAIL, f"{HEARTBEAT_ID} never received"))
    elif age > limit:
        results.append(Result("heartbeat from HA", FAIL, f"last heartbeat {age:.0f}s ago"))
    else:
        results.append(Result("heartbeat from HA", PASS, f"{age:.0f}s ago"))
    return results


# --- 3. setpoint round trip --------------------------------------------------


@dataclass
class SetpointCase:
    ehal_id: str
    entity_id: str
    kind: str
    unit: str
    current_ehal: float
    value_ehal: float

    def native(self, value_ehal: float) -> float:
        return from_ehal(self.kind, value_ehal, self.unit)


def _num_state(state: dict[str, Any] | None) -> float | None:
    try:
        return float(str((state or {}).get("state")))
    except ValueError:
        return None


def pick_setpoint_case(bench: Bench) -> SetpointCase | str:
    """A write signal with a safe test value, or a reason string."""
    writes = bench.archetype.writes()
    ordered = [i for pref in _SETPOINT_PREFERENCE for i in writes if field_kind(i) == pref]
    if not ordered:
        return "no ESS limit / EVCS current setpoint activated"
    ehal_id = ordered[0]
    kind = field_kind(ehal_id)
    entity_id = bench.archetype.placeholders[ehal_id]
    state = bench.ha.get_state(entity_id)
    native = _num_state(state)
    if native is None:
        return f"{entity_id} has no numeric state"
    attrs = state.get("attributes") or {}
    unit = str(attrs.get("unit_of_measurement") or "")
    delta = _DELTA.get(field_quantity(kind) or "")
    if delta is None:
        return f"no safe test step for {kind}"
    try:
        current = to_ehal(kind, native, unit)
        lo = to_ehal(kind, float(attrs.get("min", -1e12)), unit)
        hi = to_ehal(kind, float(attrs.get("max", 1e12)), unit)
    except UnitMismatchError as exc:
        return str(exc)
    for candidate in (current + delta, current - delta):
        if lo <= candidate <= hi:
            return SetpointCase(ehal_id, entity_id, kind, unit, current, candidate)
    return f"no value within the entity range around {current:g}"


def _ha_matches(bench: Bench, case: SetpointCase, value_ehal: float) -> bool:
    actual = _num_state(bench.ha.get_state(case.entity_id))
    expected = case.native(value_ehal)
    return actual is not None and abs(actual - expected) <= max(1.0, 0.01 * abs(expected))


def _status_matches(bench: Bench, case: SetpointCase, value_ehal: float) -> bool:
    try:
        got = bench.fetch_status().get(case.ehal_id)
    except (OSError, ValueError):
        return False
    return got is not None and abs(float(got) - value_ehal) < 0.5


def _restore(bench: Bench, case: SetpointCase, original: float | None) -> None:
    bench.publish(case.ehal_id, case.current_ehal if original is None else original)


def check_setpoint_roundtrip(bench: Bench) -> list[Result]:
    name = "setpoint round trip"
    if (skip := _need_ha(bench, name)) is not None:
        return [skip]
    case = pick_setpoint_case(bench)
    if isinstance(case, str):
        return [Result(name, SKIP, case)]
    original = bench.published_value(case.ehal_id)
    bench.log(f"round trip on {case.ehal_id}: {case.current_ehal:g} -> {case.value_ehal:g}")
    bench.publish(case.ehal_id, case.value_ehal)
    results = []
    try:
        in_status = bench.wait_until(lambda: _status_matches(bench, case, case.value_ehal))
        results.append(
            Result(
                f"{case.ehal_id} published -> status.json",
                PASS if in_status else FAIL,
                "" if in_status else f"status.json did not show {case.value_ehal:g}",
            )
        )
        in_ha = in_status and bench.wait_until(lambda: _ha_matches(bench, case, case.value_ehal))
        results.append(
            Result(
                f"status.json -> {case.entity_id}",
                PASS if in_ha else (FAIL if in_status else SKIP),
                "" if in_ha else (f"HA number did not reach {case.native(case.value_ehal):g}" if in_status else "no status.json value"),
            )
        )
    finally:
        _restore(bench, case, original)
    return results


# --- 4. negative cases -------------------------------------------------------


def check_reject_writes(bench: Bench) -> list[Result]:
    name = "reject_writes -> hub_write_failed reported to Earnie"
    if (skip := _need_ha(bench, name)) is not None:
        return [skip]
    case = pick_setpoint_case(bench)
    if isinstance(case, str):
        return [Result(name, SKIP, case)]
    original = bench.published_value(case.ehal_id)
    started = bench.now()
    bench.ha.call_service(SIM_DOMAIN, "reject_writes", {"enabled": True})
    results: list[Result] = []
    try:
        bench.publish(case.ehal_id, case.value_ehal)

        def reported() -> bool:
            row = bench.load_inbox().get(HUB_WRITE_FAILED_ID)
            stamp = (row or {}).get("last_ts")
            return bool(stamp) and datetime.fromisoformat(str(stamp)) > started

        seen = bench.wait_until(reported, 3 * bench.repeat_s + 15)
        unchanged = not _ha_matches(bench, case, case.value_ehal)
        ok = seen and unchanged
        detail = []
        if not seen:
            detail.append(f"no fresh {HUB_WRITE_FAILED_ID} push")
        if not unchanged:
            detail.append("the number changed although writes were rejected")
        results.append(Result(name, PASS if ok else FAIL, "; ".join(detail)))
    finally:
        bench.ha.call_service(SIM_DOMAIN, "reject_writes", {"enabled": False})
    healed = bench.wait_until(lambda: _ha_matches(bench, case, case.value_ehal))
    results.append(
        Result(
            "value applied after reject_writes is switched off",
            PASS if healed else FAIL,
            "" if healed else "retry did not apply the setpoint",
        )
    )
    _restore(bench, case, original)
    return results


def _pick_read(bench: Bench, predicate: Callable[[str], bool]) -> str | None:
    return next((i for i in bench.archetype.reads() if predicate(i)), None)


def check_set_unavailable(bench: Bench) -> list[Result]:
    name = "set_unavailable -> no crash, push resumes"
    if (skip := _need_ha(bench, name)) is not None:
        return [skip]
    ehal_id = _pick_read(bench, lambda i: field_kind(i) == "sens_ess_soc") or _pick_read(
        bench, lambda i: field_kind(i).startswith("sens_") and "energy" not in field_kind(i)
    )
    if ehal_id is None:
        return [Result(name, SKIP, "no read signal")]
    entity_id = bench.archetype.placeholders[ehal_id]
    minutes = 0.5
    bench.ha.call_service(SIM_DOMAIN, "set_unavailable", {"entity_id": entity_id, "minutes": minutes})
    went = bench.wait_until(
        lambda: str((bench.ha.get_state(entity_id) or {}).get("state")) == "unavailable"
    )
    if not went:
        return [Result(name, FAIL, f"{entity_id} did not become unavailable")]
    bench.sleep(2 * bench.repeat_s)
    try:
        status_ok = isinstance(bench.fetch_status(), dict)
    except (OSError, ValueError) as exc:
        return [Result(name, FAIL, f"Earnie status.json unreachable during the fault: {exc}")]
    hb = _age_s(bench.load_inbox().get(HEARTBEAT_ID), bench.now())
    if not status_ok or hb is None or hb > bench.fresh_limit_s:
        return [Result(name, FAIL, "Earnie lost the link during the fault (heartbeat stale)")]
    resumed = bench.wait_until(
        lambda: (_age_s(bench.load_inbox().get(ehal_id), bench.now()) or 1e9) <= bench.fresh_limit_s,
        minutes * 60 + 3 * bench.repeat_s + 10,
    )
    return [
        Result(
            name,
            PASS if resumed else FAIL,
            f"{ehal_id}" + ("" if resumed else " did not resume pushing after the fault"),
        )
    ]


def _automation_for(bench: Bench, ehal_id: str) -> str | None:
    wanted = f"earnie_push_{_sanitize_id(ehal_id)}"
    for state in bench.ha.list_states():
        if state["entity_id"].startswith("automation.") and (state.get("attributes") or {}).get("id") == wanted:
            return state["entity_id"]
    return None


def check_stopped_push(bench: Bench) -> list[Result]:
    power_name = "stopped power push -> 0 angenommen (verstummt)"
    energy_name = "stopped energy push -> never invented as 0"
    if (skip := _need_ha(bench, power_name)) is not None:
        return [skip, Result(energy_name, SKIP, "needs --ha-token")]
    power_id = _pick_read(
        bench,
        lambda i: field_kind(i).startswith("sens_") and "power" in field_kind(i) and "energy" not in field_kind(i),
    )
    energy_id = _pick_read(bench, lambda i: "energy" in field_kind(i))
    chosen = {i: _automation_for(bench, i) for i in (power_id, energy_id) if i}
    missing = [i for i, auto in chosen.items() if auto is None]
    if missing:
        return [Result(power_name, FAIL, f"no push automation in HA for {', '.join(missing)}")]
    for eid in chosen.values():
        bench.ha.call_service("automation", "turn_off", {"entity_id": eid})
    results: list[Result] = []
    try:
        stale_after = 3 * bench.repeat_s + FLUSH_SLACK_S

        def all_stale() -> bool:
            rows = bench.load_inbox()
            now = bench.now()
            return all((_age_s(rows.get(i), now) or 0) > stale_after for i in chosen)

        bench.wait_until(all_stale, 3 * bench.repeat_s + 30)
        rows = bench.load_inbox()
        now = bench.now()
        link = link_alive(rows, repeat_s=bench.repeat_s, now=now)
        for ehal_id, name, want_zero in ((power_id, power_name, True), (energy_id, energy_name, False)):
            if ehal_id is None:
                results.append(Result(name, SKIP, "no matching signal activated"))
                continue
            state, value = derive_state(ehal_id, rows.get(ehal_id), link=link, repeat_s=bench.repeat_s, now=now)
            if not link:
                results.append(Result(name, FAIL, "heartbeat link not alive, zero rule not applicable"))
            elif want_zero and state == STATE_ZERO_HELD:
                results.append(Result(name, SKIP, f"{ehal_id} last pushed 0, a stopped push is not visible"))
            elif want_zero:
                ok = state == STATE_ZERO_ASSUMED_SILENT
                results.append(Result(name, PASS if ok else FAIL, f"{ehal_id}: {state}"))
            else:
                ok = state not in _ZERO_STATES and value is None
                results.append(Result(name, PASS if ok else FAIL, f"{ehal_id}: {state}, value {value}"))
    finally:
        for eid in chosen.values():
            bench.ha.call_service("automation", "turn_on", {"entity_id": eid})
    return results


# --- orchestration -----------------------------------------------------------


def check_pack_unchanged(archetype: Archetype, config_dir: Path) -> Result:
    name = "pack unchanged since the archetype was generated"
    house = json.loads((config_dir / "house_profiles.json").read_text(encoding="utf-8"))
    components = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    ok = pack_sha256(house, components) == archetype.meta.get("source_pack_sha256")
    return Result(name, PASS if ok else FAIL, "" if ok else "rerun scripts.ha_testbed_build")


def run_checks(bench: Bench, *, negative: bool = True) -> list[Result]:
    results = check_ha_entities(bench) + check_inbox(bench) + check_setpoint_roundtrip(bench)
    if negative:
        results += check_reject_writes(bench)
        results += check_set_unavailable(bench)
        results += check_stopped_push(bench)
    return results


def exit_code(results: list[Result], *, require_all: bool = False) -> int:
    bad = {FAIL, SKIP} if require_all else {FAIL}
    return 1 if any(r.status in bad for r in results) else 0


def format_table(results: list[Result]) -> str:
    width = max((len(r.name) for r in results), default=0)
    lines = [f"{r.status:<4}  {r.name:<{width}}  {r.detail}".rstrip() for r in results]
    counts = {s: sum(r.status == s for r in results) for s in (PASS, FAIL, SKIP)}
    lines.append(f"\n{counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped")
    return "\n".join(lines)


def _make_bench(args: argparse.Namespace, archetype: Archetype) -> Bench:
    runtime_dir = args.runtime_dir
    os.environ["EARNIE_RUNTIME_PATH"] = str(runtime_dir)
    # Imported after the runtime path is set: the ledger / inbox resolve it per call.
    from integrations import ehal_write
    from runtime_store import ehal_push_inbox

    token = args.ha_token or os.environ.get("HA_TESTBED_TOKEN", "")

    def fetch_status() -> dict[str, Any]:
        with urllib.request.urlopen(args.earnie_url.rstrip("/") + "/ehal/status.json", timeout=10) as resp:  # noqa: S310
            return json.loads(resp.read())

    def publish(qid: str, value: float) -> None:
        ehal_write.write_field(qid, value)

    return Bench(
        archetype=archetype,
        repeat_s=args.repeat_s or expected_repeat_s(),
        timeout_s=args.timeout_s,
        ha=HaApi(args.ha_url, token) if token else None,
        load_inbox=ehal_push_inbox.load_inbox,
        fetch_status=fetch_status,
        publish=publish,
        published_value=lambda qid: ehal_write.load_published().get(qid),
        log=lambda msg: print(f"  .. {msg}", file=sys.stderr),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HA contract testbed check (HA Testbed P4)")
    parser.add_argument("--testbed-dir", type=Path, default=DEFAULT_TESTBED_DIR)
    parser.add_argument("--name", default=DEFAULT_ARCHETYPE_NAME, help="archetype name used in HA")
    parser.add_argument("--archetype-dir", type=Path, help="default: <testbed>/homeassistant/earnie_house_sim/archetypes/<name>")
    parser.add_argument("--config-dir", type=Path, help="Earnie pack: also verify it matches the archetype")
    parser.add_argument("--runtime-dir", type=Path, help="Earnie runtime dir (default: <testbed>/runtime)")
    parser.add_argument("--earnie-url", default="http://127.0.0.1:8541")
    parser.add_argument("--ha-url", default="http://127.0.0.1:8123")
    parser.add_argument("--ha-token", default="", help="HA long-lived token (or env HA_TESTBED_TOKEN)")
    parser.add_argument("--repeat-s", type=float, default=None, help="push cadence (default: EARNIE_PUSH_REPEAT_S or 10)")
    parser.add_argument("--timeout-s", type=float, default=90.0, help="wait limit per step")
    parser.add_argument("--skip-negative", action="store_true")
    parser.add_argument("--require-all", action="store_true", help="count SKIP as failure")
    args = parser.parse_args(argv)
    testbed_dir = args.testbed_dir.resolve()
    args.runtime_dir = (args.runtime_dir or testbed_dir / "runtime").resolve()
    archetype_dir = args.archetype_dir or ha_dir(testbed_dir) / ARCHETYPES_RELPATH / args.name
    try:
        archetype = Archetype.load(archetype_dir)
        extra = [check_pack_unchanged(archetype, args.config_dir)] if args.config_dir else []
        bench = _make_bench(args, archetype)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: cannot load the generated archetype from {archetype_dir}: {exc}", file=sys.stderr)
        return 2
    results = extra + run_checks(bench, negative=not args.skip_negative)
    print(format_table(results))
    return exit_code(results, require_all=args.require_all)


if __name__ == "__main__":
    raise SystemExit(main())
