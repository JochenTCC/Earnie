"""HouseSim multi-EV M3: dynamic EV ↔ wallbox assignment end to end over the HA push path.

Fixture ``evcc_multi_ev``: two evcc loadpoints ``lp1`` / ``lp2`` and three cars; ``car_a``
and ``car_b`` report their own plug state and charge power, ``car_c`` has no such sensors.
All three may use both wallboxes (``wallbox_assignment.mode: dynamic``).

Earnie reads the wallbox and car sensors from its push inbox, the assignment driver
(``integrations.ev_assignment_live``) runs the state machine and writes the test charge and
the ``unknown_vehicle`` policy, the planned current of an assigned car goes to its wallbox
(``evcs.<Wallbox>.*``). The bridge plays the HA carrier automations.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import config
from house_config.ha_ehal_bindings import aggregate_ha_entities
from house_config.wallboxes import normalize_wallbox, resolve_dynamic_ev_view
from house_sim.archetype import load_archetype
from house_sim.contract import build_contract
from house_sim.core.physics import ScenarioOverlay
from house_sim.push_harness import PushClient, push_cycle
from house_sim.stepper import run_ticks
from house_sim.vendor_bridge import Link, VendorBridge, plug_state_to_number
from integrations import ehal_live
from integrations import ehal_write as ew
from integrations import ev_assignment_live as eal
from integrations import loxone_request_http as http_mod
from integrations.ha_adapter import HaAdapter, HaConfig
from integrations.ha_push_read import setpoint_qualified_ids
from optimizer.ev_assignment import (
    EVIDENCE_PLUG_MATCH,
    EVIDENCE_TEST_CHARGE,
    EVIDENCE_USER_PICK,
    STATUS_ASSIGNED,
    STATUS_FREE,
    STATUS_PLUGGED_UNKNOWN,
    STATUS_TESTING,
    AssignmentSettings,
)
from runtime_store import ev_assignments as store
from runtime_store import loxone_push_inbox as inbox

TOKEN = "contract-test-token"
T0 = datetime(2026, 11, 9, 18, 0, 0)
DT_H = 10.0 / 3600.0  # one HouseSim tick = 10 s
PLUGGED = {"active": True, "plugged_in": True}


def _wallbox(wallbox_id: str, policy: str) -> dict:
    return normalize_wallbox(
        {
            "id": wallbox_id,
            "voltage_v": 230,
            "phases": 3,
            "min_current_a": 6,
            "max_current_a": 16,
            "unknown_vehicle": policy,
            "ehal_bindings": {
                f"evcs.{wallbox_id}.set_evcs_max_current": "",
                f"evcs.{wallbox_id}.sens_evcs_connected": "",
                f"evcs.{wallbox_id}.sens_evcs_active_power": "",
            },
        },
        index=0,
    )


def _ev(ev_id: str, *, phases: int, sensors: bool, wallboxes: dict) -> dict:
    """Dynamic EV as the loader hands it to the runtime (no wallbox of its own)."""
    spec = {
        "id": ev_id,
        "name": ev_id,
        "label": ev_id,
        "type": "ev",
        "phases": phases,
        "min_current_a": 6.0,
        "max_current_a": 16.0,
        "wallbox_assignment": {"mode": "dynamic", "wallbox_ids": ["lp1", "lp2"]},
        "battery_capacity_kwh": 60.0,
        "charging_schedule": {"forecast_when_absent": False, "target_soc_percent": 100.0},
        "ehal_bindings": (
            {f"ev.{ev_id}.sens_ev_connected": "", f"ev.{ev_id}.sens_ev_charge_power": ""}
            if sensors
            else {}
        ),
    }
    resolve_dynamic_ev_view(spec, wallboxes, label=ev_id)
    return spec


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setenv(http_mod.PUSH_TOKEN_ENV, TOKEN)
    inbox.reset_memory_for_tests()
    ew.clear_published_for_tests()
    http_mod.stop_loxone_request_http()
    eal.reset_for_tests(AssignmentSettings(match_window_sec=300.0, test_duration_sec=120.0))
    yield
    http_mod.stop_loxone_request_http()
    inbox.reset_memory_for_tests()
    ew.clear_published_for_tests()
    store.set_live_assignments(None)
    eal.reset_for_tests()


class Bench:
    def __init__(self, monkeypatch, *, policies: dict[str, str]) -> None:
        wallboxes = {wid: _wallbox(wid, policy) for wid, policy in policies.items()}
        self.consumers = [
            _ev("car_a", phases=3, sensors=True, wallboxes=wallboxes),
            _ev("car_b", phases=1, sensors=True, wallboxes=wallboxes),
            _ev("car_c", phases=3, sensors=False, wallboxes=wallboxes),
        ]

        def _consumers(optimizer_only: bool = False, *, raw_dynamic: bool = False) -> list:
            items = [dict(c) for c in self.consumers]
            return items if raw_dynamic else store.apply_live_assignments(items)

        monkeypatch.setattr(config, "get_flexible_consumers", _consumers)
        house = {
            "plant": {"ehal_bindings": {"sens_grid_power_active": ""}},
            "profiles": {"standard": {"consumers": self.consumers}},
        }
        components = {"batteries": [], "inverters": [], "pv_systems": []}
        self.adapter = HaAdapter(
            HaConfig(
                base_url="",
                token="",
                adapter_id="house-sim",
                entities=aggregate_ha_entities(house, components_doc=components),
                setpoint_qids=setpoint_qualified_ids(house, components),
            )
        )
        monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
        monkeypatch.setattr(ehal_live, "get_network_adapter", lambda: self.adapter)
        # The bench writes setpoints (loud); the fixture config is silent.
        from runtime_store.shadow import hooks

        monkeypatch.setattr(hooks, "should_invoke_setpoint_writes", lambda **_kw: True)
        self.package = load_archetype("evcc_multi_ev")
        self.vendor = self.package.build_store()
        plug = plug_state_to_number
        telemetry = []
        for n, wid in ((1, "lp1"), (2, "lp2")):
            telemetry += [
                Link(f"evcs.{wid}.sens_evcs_connected", f"binary_sensor.evcc_loadpoint_{n}_connected", plug),
                Link(f"evcs.{wid}.sens_evcs_active_power", f"sensor.evcc_loadpoint_{n}_charge_power"),
            ]
        for car in ("car_a", "car_b"):
            telemetry += [
                Link(f"ev.{car}.sens_ev_connected", f"binary_sensor.{car}_plugged", plug),
                Link(f"ev.{car}.sens_ev_charge_power", f"sensor.{car}_charge_power"),
            ]
        self.bridge = VendorBridge(
            build_contract(house, components),
            self.vendor,
            setpoints=[
                Link("evcs.lp1.set_evcs_max_current", "number.evcc_loadpoint_1_max_current"),
                Link("evcs.lp2.set_evcs_max_current", "number.evcc_loadpoint_2_max_current"),
            ],
            telemetry=telemetry,
        )
        server = http_mod.start_loxone_request_http(0, host="127.0.0.1")
        self.client = PushClient(f"http://127.0.0.1:{server.server_address[1]}", token=TOKEN)
        self.overlay = ScenarioOverlay()
        self.physics = None

    def sim(self) -> None:
        """Earnie's published setpoints → vendor, one HouseSim tick, telemetry → Earnie."""
        push_cycle(self.bridge.bundle, self.client)
        self.bridge.to_vendor()
        self.physics = run_ticks(
            self.package,
            self.vendor,
            n_ticks=1,
            dt_h=DT_H,
            physics=self.physics,
            overlay=self.overlay,
        )
        self.bridge.from_vendor()
        push_cycle(self.bridge.bundle, self.client)

    def cycle_writes(self, consumer_powers: dict[str, float] | None = None) -> list[dict]:
        """Earnie's EVCS writes of one cycle: planned pairs, then the unassigned wallboxes."""
        powers = consumer_powers or {}
        _err, rows = ehal_live.write_evcs_max_current_from_consumers(
            powers, {ev: PLUGGED for ev in powers}, {}
        )
        _err2, policy_rows = eal.write_unassigned_wallboxes()
        return list(rows) + list(policy_rows)

    def current(self, n: int) -> float:
        return self.vendor.numeric_state(f"number.evcc_loadpoint_{n}_max_current")

    def state(self, wallbox_id: str):
        return eal.engine().states[wallbox_id]


def _start(bench: Bench) -> None:
    eal.start()
    eal.tick(T0)
    bench.cycle_writes()
    bench.sim()
    eal.tick(T0 + timedelta(seconds=5))


def test_plug_match_assigns_and_the_plan_follows_the_wallbox(monkeypatch):
    bench = Bench(monkeypatch, policies={"lp1": "off", "lp2": "off"})
    _start(bench)
    assert bench.current(1) == pytest.approx(0.0)
    assert config.get_flexible_consumers() == []  # no car assigned → none planned

    bench.overlay.car_arrives(wallbox="lp1", ev="car_a")
    bench.sim()
    eal.tick(T0 + timedelta(seconds=10))
    assert bench.state("lp1").status == STATUS_PLUGGED_UNKNOWN
    eal.tick(T0 + timedelta(seconds=311))
    assert (bench.state("lp1").status, bench.state("lp1").ev_id) == (STATUS_ASSIGNED, "car_a")
    assert bench.state("lp1").evidence == EVIDENCE_PLUG_MATCH

    planned = config.get_flexible_consumers()
    assert [(c["id"], c["charger_id"]) for c in planned] == [("car_a", "lp1")]
    rows = bench.cycle_writes({"car_a": 6.9})  # 10 A × 230 V × 3
    fields = {row["field"]: row["value"] for row in rows}
    assert fields["evcs.lp1.set_evcs_max_current"] == pytest.approx(10.0)
    # lp2 is free and follows its policy "off".
    assert fields["evcs.lp2.set_evcs_max_current"] == pytest.approx(0.0)
    bench.sim()
    assert bench.current(1) == pytest.approx(10.0)
    power, _ = inbox.read_push_value("ev.car_a.sens_ev_charge_power")
    assert power == pytest.approx(6900.0)

    snapshot = json.loads(
        open(store._path(store.ASSIGNMENTS_FILENAME), encoding="utf-8").read()
    )
    row = next(r for r in snapshot["wallboxes"] if r["wallbox_id"] == "lp1")
    assert (row["status"], row["ev_id"], row["evidence"]) == ("assigned", "car_a", "plug_match")

    bench.overlay.car_leaves(wallbox="lp1")
    bench.sim()
    eal.tick(T0 + timedelta(seconds=400))
    assert bench.state("lp1").status == STATUS_FREE
    assert config.get_flexible_consumers() == []


def test_ambiguous_plug_goes_to_the_test_charge_and_restart_rebinds(monkeypatch):
    bench = Bench(monkeypatch, policies={"lp1": "off", "lp2": "off"})
    _start(bench)
    bench.overlay.car_arrives(wallbox="lp1", ev="car_b")
    bench.overlay.car_arrives(wallbox="lp2", ev="car_a")
    bench.sim()
    eal.tick(T0 + timedelta(seconds=10))
    eal.tick(T0 + timedelta(seconds=311))
    # Both cars plugged at the same time: no plug match; one test at a time, lp1 first.
    assert bench.state("lp1").status == STATUS_TESTING
    assert bench.state("lp2").status == STATUS_PLUGGED_UNKNOWN
    assert bench.current(1) == pytest.approx(0.0)  # test current is published, not yet applied
    bench.sim()
    assert bench.current(1) == pytest.approx(6.0)
    eal.tick(T0 + timedelta(seconds=321))
    assert (bench.state("lp1").ev_id, bench.state("lp1").evidence) == (
        "car_b",
        EVIDENCE_TEST_CHARGE,
    )
    assert bench.state("lp2").status == STATUS_TESTING
    bench.sim()
    assert bench.current(1) == pytest.approx(0.0)  # test ended
    eal.tick(T0 + timedelta(seconds=331))
    assert (bench.state("lp2").ev_id, bench.state("lp2").evidence) == (
        "car_a",
        EVIDENCE_TEST_CHARGE,
    )

    # Daemon restart: assignments are dropped and found again (D7).
    bench.sim()
    eal.start()
    assert config.get_flexible_consumers() == []
    eal.tick(T0 + timedelta(seconds=400))
    assert bench.state("lp1").status == STATUS_TESTING
    assert bench.state("lp1").plugged_at is None  # plugged before the start: no plug edge
    bench.sim()
    eal.tick(T0 + timedelta(seconds=410))
    assert bench.state("lp1").ev_id == "car_b"
    bench.sim()
    eal.tick(T0 + timedelta(seconds=420))
    bench.sim()
    eal.tick(T0 + timedelta(seconds=430))
    assert eal.engine().assignments() == {"car_b": "lp1", "car_a": "lp2"}


def test_car_without_sensors_charges_by_policy_until_the_user_picks_it(monkeypatch):
    bench = Bench(monkeypatch, policies={"lp1": "off", "lp2": "immediate"})
    _start(bench)
    assert bench.current(2) == pytest.approx(16.0)

    bench.overlay.car_arrives(wallbox="lp2", ev="car_c")
    bench.sim()
    eal.tick(T0 + timedelta(seconds=10))
    eal.tick(T0 + timedelta(seconds=311))
    state = bench.state("lp2")
    assert state.status == STATUS_PLUGGED_UNKNOWN
    assert state.note == "Probeladung nicht möglich (kein Auto mit Ladeleistungs-Sensor)"
    # The unknown car charges as the wallbox's policy says: immediate = maximum current.
    rows = {r["field"]: r["value"] for r in bench.cycle_writes()}
    assert rows["evcs.lp2.set_evcs_max_current"] == pytest.approx(16.0)
    bench.sim()
    power, _ = inbox.read_push_value("evcs.lp2.sens_evcs_active_power")
    assert power == pytest.approx(16 * 230.0 * 3)

    store.request_pick("lp2", "car_c", state.session)
    eal.tick(T0 + timedelta(seconds=320))
    assert (bench.state("lp2").ev_id, bench.state("lp2").evidence) == (
        "car_c",
        EVIDENCE_USER_PICK,
    )
    rows = {r["field"]: r["value"] for r in bench.cycle_writes({"car_c": 4.14})}
    assert rows["evcs.lp2.set_evcs_max_current"] == pytest.approx(6.0)
    assert rows["evcs.lp1.set_evcs_max_current"] == pytest.approx(0.0)
