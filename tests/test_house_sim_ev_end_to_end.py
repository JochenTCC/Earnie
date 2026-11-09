"""HouseSim W3: one EV end to end over the push path.

Earnie publishes ``set_evcs_max_current`` → the push harness applies it to the
contract entity → the bridge (role of the HA carrier automations) copies it onto
the evcc loadpoint of ``evcc_en`` → HouseSim charges the car → the bridge copies
charge power, plug state and car SoC back → the push harness pushes them into
Earnie's inbox → Earnie's own EV read path sees the new SoC and plug state.
"""
from __future__ import annotations

import pytest

from house_sim.archetype import load_archetype
from house_sim.contract import build_contract
from house_sim.core.physics import ScenarioOverlay
from house_sim.push_harness import PushClient, push_cycle
from house_sim.stepper import run_ticks
from house_sim.vendor_bridge import Link, VendorBridge, plug_state_to_number
from integrations import ehal_live
from integrations import ehal_write as ew
from integrations import loxone_request_http as http_mod
from optimizer.ev_soc_tracking import fetch_loxone_actual_soc_percent
from runtime_store import loxone_push_inbox as inbox
from settings.ehal_marker_resolve import marker_sens_evcs_connected
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere

TOKEN = "contract-test-token"

EV_CONSUMER = {
    "id": "car_a",
    "label": "E-Auto",
    "type": "ev",
    "nominal_power_kw": 11.04,
    "min_power_kw": 4.14,
    "battery_capacity_kwh": 60.0,
    "charging_schedule": {
        "target_soc_percent": 100.0,
        "nominal_power_voltage_v": 230.0,
        "nominal_power_phases": 3,
    },
    "ehal_bindings": {
        "evcs.car_a.set_evcs_max_current": "",
        "evcs.car_a.sens_evcs_active_power": "",
        "evcs.car_a.sens_evcs_connected": "",
        "ev.car_a.sens_evcs_soc_act": "",
    },
}


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
def loop():
    house = {
        "plant": {"ehal_bindings": {"sens_grid_power_active": ""}},
        "profiles": {"standard": {"consumers": [EV_CONSUMER]}},
    }
    components = {"batteries": [], "inverters": [], "pv_systems": []}
    bundle = build_contract(house, components)
    package = load_archetype("evcc_en")
    vendor = package.build_store()
    bridge = VendorBridge(
        bundle,
        vendor,
        setpoints=[
            Link("evcs.car_a.set_evcs_max_current", "number.evcc_loadpoint_1_max_current"),
        ],
        telemetry=[
            Link("grid.meter.sens_grid_power_active", "sensor.evcc_grid_power"),
            Link("evcs.car_a.sens_evcs_active_power", "sensor.evcc_loadpoint_1_charge_power"),
            Link(
                "evcs.car_a.sens_evcs_connected",
                "binary_sensor.evcc_loadpoint_1_connected",
                convert=plug_state_to_number,
            ),
            Link("ev.car_a.sens_evcs_soc_act", "sensor.evcc_car_a_soc"),
        ],
    )
    server = http_mod.start_loxone_request_http(0, host="127.0.0.1")
    client = PushClient(f"http://127.0.0.1:{server.server_address[1]}", token=TOKEN)
    return package, vendor, bundle, bridge, client


def _cycle(package, vendor, bridge, client, *, overlay=None, physics=None, n_ticks=1):
    """Earnie status → vendor, simulate, vendor → Earnie inbox."""
    report = push_cycle(bridge.bundle, client)  # pushes old telemetry, applies setpoints
    bridge.to_vendor()
    state = run_ticks(
        package, vendor, n_ticks=n_ticks, dt_h=0.25, overlay=overlay, physics=physics
    )
    bridge.from_vendor()
    push_cycle(bridge.bundle, client)  # pushes the new telemetry
    return state, report


def test_earnie_current_charges_the_car_and_earnie_reads_soc_and_plug(loop):
    package, vendor, bundle, bridge, client = loop
    assert sorted(bundle.write_entity_by_ehal) == ["evcs.car_a.set_evcs_max_current"]

    # Earnie's EV write converts planned kW into current with the consumer's
    # voltage and phases (integrations/ehal_live.write_evcs_max_current_from_consumers).
    voltage_v, phases = ev_nominal_power_conversion(EV_CONSUMER)
    amps = kw_to_ampere(6.9, voltage_v=voltage_v, phases=phases)
    assert amps == pytest.approx(10.0)
    ew.write_field("evcs.car_a.set_evcs_max_current", amps)

    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    state, report = _cycle(package, vendor, bridge, client, overlay=overlay)

    assert "evcs.car_a.set_evcs_max_current" in report["setpoints_applied"]
    assert vendor.numeric_state("number.evcc_loadpoint_1_max_current") == pytest.approx(10.0)
    assert state.evcs_power_w == pytest.approx(6900.0)

    power, power_state = inbox.read_push_value("evcs.car_a.sens_evcs_active_power")
    assert power_state == inbox.STATE_OK
    assert power == pytest.approx(6900.0)
    grid, _ = inbox.read_push_value("grid.meter.sens_grid_power_active")
    assert grid == pytest.approx((1.5 + 6.9 - 1.2) * 1000.0)

    # Earnie's own read path for the planner's charging context.
    expected_soc = 45.0 + 6.9 * 0.25 / 60.0 * 100.0
    # The % sensor carries two decimals.
    assert fetch_loxone_actual_soc_percent(EV_CONSUMER) == pytest.approx(expected_soc, abs=0.006)
    plug = ehal_live.read_generic_value(marker_sens_evcs_connected(EV_CONSUMER))
    assert plug == pytest.approx(1.0)


def test_earnie_zero_current_stops_charging_and_unplug_is_seen(loop):
    package, vendor, _bundle, bridge, client = loop
    ew.write_field("evcs.car_a.set_evcs_max_current", 16.0)
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    state, _ = _cycle(package, vendor, bridge, client, overlay=overlay)
    assert state.evcs_power_w == pytest.approx(11040.0)
    soc_after_charge = fetch_loxone_actual_soc_percent(EV_CONSUMER)

    # Earnie writes 0 A: below the loadpoint's minimum, so the car stops.
    ew.write_field("evcs.car_a.set_evcs_max_current", 0.0)
    state, _ = _cycle(package, vendor, bridge, client, physics=state)
    assert state.evcs_power_w == 0.0
    power, _ = inbox.read_push_value("evcs.car_a.sens_evcs_active_power")
    assert power == pytest.approx(0.0)
    assert fetch_loxone_actual_soc_percent(EV_CONSUMER) == pytest.approx(soc_after_charge)

    overlay.car_leaves(wallbox="lp1")
    _cycle(package, vendor, bridge, client, overlay=overlay, physics=state)
    plug = ehal_live.read_generic_value(marker_sens_evcs_connected(EV_CONSUMER))
    assert plug == pytest.approx(0.0)


def test_bridge_rejects_links_that_are_not_activated(loop):
    _package, vendor, bundle, _bridge, _client = loop
    with pytest.raises(ValueError, match="no activated write signal"):
        VendorBridge(
            bundle,
            vendor,
            setpoints=[Link("evcs.car_a.set_evcs_mode", "switch.evcc_loadpoint_1_enable")],
            telemetry=[],
        )
    with pytest.raises(ValueError, match="neither"):
        plug_state_to_number("maybe")
