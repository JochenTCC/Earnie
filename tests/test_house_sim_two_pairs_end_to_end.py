"""HouseSim multi-EV M2: two fixed EV ↔ wallbox pairs end to end over the HA push path.

Earnie's live EVCS write (``ehal_live.write_evcs_max_current_from_consumers``) publishes one
current per pair with the pair's own voltage and phases → the push harness applies them →
the bridge copies them onto two evcc loadpoints → HouseSim charges both cars → charge power
comes back per wallbox. The second loadpoint and car are a copy of ``evcc_en``'s first,
built in memory (the shipped fixture keeps one loadpoint).
"""
from __future__ import annotations

import copy
import dataclasses
import json

import pytest

from house_config.ha_ehal_bindings import aggregate_ha_entities
from house_sim.archetype import load_archetype
from house_sim.contract import build_contract
from house_sim.core.physics import ScenarioOverlay
from house_sim.push_harness import PushClient, push_cycle
from house_sim.stepper import run_ticks
from house_sim.vendor_bridge import Link, VendorBridge
from integrations import ehal_live
from integrations import ehal_write as ew
from integrations import loxone_request_http as http_mod
from integrations.ha_adapter import HaAdapter, HaConfig
from integrations.ha_push_read import setpoint_qualified_ids
from runtime_store import loxone_push_inbox as inbox

TOKEN = "contract-test-token"


def _ev(ev_id: str, *, phases: int) -> dict:
    """EV consumer as the loader's pair view hands it to the runtime (fixed wallbox)."""
    return {
        "id": ev_id,
        "label": ev_id,
        "type": "ev",
        # Pair limits 6–16 A at 230 V (resolve_ev_pair).
        "nominal_power_kw": 16 * 230.0 * phases / 1000.0,
        "min_power_kw": 6 * 230.0 * phases / 1000.0,
        "battery_capacity_kwh": 60.0,
        "charging_schedule": {
            "target_soc_percent": 100.0,
            "nominal_power_voltage_v": 230.0,
            "nominal_power_phases": phases,
        },
        "ehal_bindings": {
            f"evcs.{ev_id}.set_evcs_max_current": "",
            f"evcs.{ev_id}.sens_evcs_active_power": "",
        },
    }


CAR_A = _ev("car_a", phases=3)  # 3-phase car at loadpoint 1
CAR_B = _ev("car_b", phases=1)  # 1-phase car at loadpoint 2: the pair charges on one phase


def _two_loadpoint_package():
    """``evcc_en`` with a second loadpoint ``lp2`` and car ``car_b`` (copies of the first)."""
    package = load_archetype("evcc_en")
    rename = {"loadpoint_1": "loadpoint_2", "car_a": "car_b", "Car A": "Car B"}

    def _copy(raw):
        text = json.dumps(raw)
        for old, new in rename.items():
            text = text.replace(old, new)
        return json.loads(text)

    entities = list(package.entities)
    entities += [
        _copy(entity)
        for entity in package.entities
        if "loadpoint_1" in entity["entity_id"] or "car_a" in entity["entity_id"]
    ]
    params = copy.deepcopy(package.house_params)
    wallbox_b = _copy(params["wallboxes"][0])
    wallbox_b["id"] = "lp2"
    car_b = _copy(params["evs"][0])
    car_b["phases"] = 1
    params["wallboxes"].append(wallbox_b)
    params["evs"].append(car_b)
    return dataclasses.replace(package, entities=entities, house_params=params)


@pytest.fixture(autouse=True)
def _reset_push(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setenv(http_mod.PUSH_TOKEN_ENV, TOKEN)
    inbox.reset_memory_for_tests()
    ew.clear_published_for_tests()
    http_mod.stop_loxone_request_http()
    yield
    http_mod.stop_loxone_request_http()
    inbox.reset_memory_for_tests()
    ew.clear_published_for_tests()


@pytest.fixture
def loop(monkeypatch):
    house = {
        "plant": {"ehal_bindings": {"sens_grid_power_active": ""}},
        "profiles": {"standard": {"consumers": [CAR_A, CAR_B]}},
    }
    components = {"batteries": [], "inverters": [], "pv_systems": []}
    adapter = HaAdapter(
        HaConfig(
            base_url="",
            token="",
            adapter_id="house-sim",
            entities=aggregate_ha_entities(house, components_doc=components),
            setpoint_qids=setpoint_qualified_ids(house, components),
        )
    )
    monkeypatch.setattr(ehal_live, "is_ha_backend", lambda: True)
    monkeypatch.setattr(ehal_live, "get_network_adapter", lambda: adapter)
    monkeypatch.setattr(ehal_live, "live_ev_consumers", lambda: [CAR_A, CAR_B])
    bundle = build_contract(house, components)
    package = _two_loadpoint_package()
    vendor = package.build_store()
    bridge = VendorBridge(
        bundle,
        vendor,
        setpoints=[
            Link("evcs.car_a.set_evcs_max_current", "number.evcc_loadpoint_1_max_current"),
            Link("evcs.car_b.set_evcs_max_current", "number.evcc_loadpoint_2_max_current"),
        ],
        telemetry=[
            Link("evcs.car_a.sens_evcs_active_power", "sensor.evcc_loadpoint_1_charge_power"),
            Link("evcs.car_b.sens_evcs_active_power", "sensor.evcc_loadpoint_2_charge_power"),
        ],
    )
    server = http_mod.start_loxone_request_http(0, host="127.0.0.1")
    client = PushClient(f"http://127.0.0.1:{server.server_address[1]}", token=TOKEN)
    return package, vendor, bridge, client


def _cycle(package, vendor, bridge, client, *, overlay):
    report = push_cycle(bridge.bundle, client)
    bridge.to_vendor()
    state = run_ticks(package, vendor, n_ticks=1, dt_h=0.25, overlay=overlay)
    bridge.from_vendor()
    push_cycle(bridge.bundle, client)
    return state, report


def test_two_pairs_charge_with_their_own_current_and_phases(loop):
    package, vendor, bridge, client = loop
    plugged = {"active": True, "plugged_in": True}
    # 6.9 kW on 3 phases and 2.3 kW on 1 phase are both 10 A at 230 V.
    error, rows = ehal_live.write_evcs_max_current_from_consumers(
        {"car_a": 6.9, "car_b": 2.3}, {"car_a": plugged, "car_b": plugged}, {}
    )
    assert error is None
    assert {row["field"] for row in rows} == {
        "evcs.car_a.set_evcs_max_current",
        "evcs.car_b.set_evcs_max_current",
    }

    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    overlay.car_arrives(wallbox="lp2", ev="car_b")
    state, report = _cycle(package, vendor, bridge, client, overlay=overlay)

    assert set(report["setpoints_applied"]) >= {
        "evcs.car_a.set_evcs_max_current",
        "evcs.car_b.set_evcs_max_current",
    }
    assert vendor.numeric_state("number.evcc_loadpoint_1_max_current") == pytest.approx(10.0)
    assert vendor.numeric_state("number.evcc_loadpoint_2_max_current") == pytest.approx(10.0)
    power_a, _ = inbox.read_push_value("evcs.car_a.sens_evcs_active_power")
    power_b, _ = inbox.read_push_value("evcs.car_b.sens_evcs_active_power")
    assert power_a == pytest.approx(6900.0)
    assert power_b == pytest.approx(2300.0)
    assert state.evcs_power_w == pytest.approx(9200.0)


def test_a_failing_charger_does_not_stop_the_other(loop, monkeypatch):
    adapter = ehal_live.get_network_adapter()
    real_write = adapter._try_setpoint_write

    def _fail_car_a(key, value):
        if key.startswith("evcs.car_a."):
            return False, None, f"EHAL publish rejected for {key}"
        return real_write(key, value)

    monkeypatch.setattr(adapter, "_try_setpoint_write", _fail_car_a)
    plugged = {"active": True, "plugged_in": True}
    powers = {"car_a": 6.9, "car_b": 2.3}
    contexts = {"car_a": plugged, "car_b": plugged}

    error, rows = ehal_live.write_evcs_max_current_from_consumers(powers, contexts, {})

    assert error is not None and error["failed_fields"] == ["set_evcs_max_current"]
    by_field = {row["field"]: row["success"] for row in rows}
    assert by_field == {
        "evcs.car_a.set_evcs_max_current": False,
        "evcs.car_b.set_evcs_max_current": True,
    }
    assert ew.load_published()["evcs.car_b.set_evcs_max_current"] == pytest.approx(10.0)
    # The next cycle still writes car_b; car_a stays disabled until the adapter is rebuilt.
    ew.clear_published_for_tests()
    ehal_live.write_evcs_max_current_from_consumers(powers, contexts, {})
    assert "evcs.car_b.set_evcs_max_current" in ew.load_published()
    assert "evcs.car_a.set_evcs_max_current" not in ew.load_published()
