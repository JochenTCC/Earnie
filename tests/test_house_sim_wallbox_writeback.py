"""HouseSim wallbox write-back W2: vendor entities in, telemetry out (S1–S3 store)."""
from __future__ import annotations

from dataclasses import replace

import pytest

from house_sim.archetype import load_archetype
from house_sim.core.evcs import (
    EvcsState,
    evcs_state_from_dict,
    parse_evs,
    parse_wallboxes,
)
from house_sim.core.physics import ScenarioOverlay, wallbox_setpoints_from_lookup
from house_sim.stepper import initial_physics, run_ticks, wallbox_setpoints_from_store


def _arrive(wallbox: str, ev: str = "car_a", soc_pct: float | None = None) -> ScenarioOverlay:
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox=wallbox, ev=ev, soc_pct=soc_pct)
    return overlay


def _tick(package, store, overlay=None, n_ticks=1, physics=None):
    return run_ticks(
        package, store, n_ticks=n_ticks, dt_h=0.25, overlay=overlay, physics=physics
    )


# --- evcc: max_current + enable switch, plug, vehicle name, car SoC ----------------


def test_evcc_written_current_drives_power_sensor_and_grid():
    package = load_archetype("evcc_en")
    store = package.build_store()
    status, _ = store.apply_service(
        "number", "set_value", {"entity_id": "number.evcc_loadpoint_1_max_current", "value": 10}
    )
    assert status == 200
    state = _tick(package, store, _arrive("lp1"))
    power_w = 10.0 * 230.0 * 3
    assert state.evcs_power_w == pytest.approx(power_w)
    assert store.numeric_state("sensor.evcc_loadpoint_1_charge_power") == pytest.approx(power_w)
    # Grid sensor follows the wallbox load in the same tick (base 1.5 kW, PV 1.2 kW).
    assert store.numeric_state("sensor.evcc_grid_power") == pytest.approx(
        (1.5 + power_w / 1000.0 - 1.2) * 1000.0
    )


def test_evcc_plug_vehicle_and_car_soc_entities():
    package = load_archetype("evcc_en")
    store = package.build_store()
    _tick(package, store)
    assert store.text_state("binary_sensor.evcc_loadpoint_1_connected") == "off"
    assert store.text_state("sensor.evcc_loadpoint_1_vehicle_name") == ""
    state = _tick(package, store, _arrive("lp1"))
    assert store.text_state("binary_sensor.evcc_loadpoint_1_connected") == "on"
    assert store.text_state("sensor.evcc_loadpoint_1_vehicle_name") == "Car A"
    # Fixture current 16 A, car limit 16 A, 3 phases → 11.04 kW for 0.25 h into 60 kWh.
    expected_soc = 45.0 + 11.04 * 0.25 / 60.0 * 100.0
    assert state.evcs.ev_soc_pct["car_a"] == pytest.approx(expected_soc)
    assert store.numeric_state("sensor.evcc_car_a_soc") == pytest.approx(expected_soc, abs=1e-6)


def test_evcc_enable_switch_off_stops_charging():
    package = load_archetype("evcc_en")
    store = package.build_store()
    store.set_state("switch.evcc_loadpoint_1_enable", "off")
    state = _tick(package, store, _arrive("lp1"))
    assert state.evcs_power_w == 0.0
    assert store.numeric_state("sensor.evcc_loadpoint_1_charge_power") == 0.0


def test_evcc_current_out_of_entity_range_is_rejected_like_ha():
    package = load_archetype("evcc_en")
    store = package.build_store()
    status, _ = store.apply_service(
        "number", "set_value", {"entity_id": "number.evcc_loadpoint_1_max_current", "value": 40}
    )
    assert status == 400


def test_unplug_clears_plug_sensor_and_power():
    package = load_archetype("evcc_en")
    store = package.build_store()
    state = _tick(package, store, _arrive("lp1"))
    overlay = ScenarioOverlay()
    overlay.car_leaves(wallbox="lp1")
    state = _tick(package, store, overlay, physics=state)
    assert state.evcs_power_w == 0.0
    assert store.text_state("binary_sensor.evcc_loadpoint_1_connected") == "off"
    assert store.numeric_state("sensor.evcc_loadpoint_1_charge_power") == 0.0


# --- go-e / Wattpilot: amp + frc, car status ---------------------------------------


def test_wattpilot_amp_and_car_status():
    package = load_archetype("fronius_de")
    store = package.build_store()
    _tick(package, store)
    assert store.text_state("sensor.goe_91234567_car") == "1"  # no car
    store.apply_service("number", "set_value", {"entity_id": "number.goe_91234567_amp", "value": 8})
    state = _tick(package, store, _arrive("wattpilot"))
    assert state.evcs_power_w == pytest.approx(8.0 * 230.0 * 3)
    assert store.numeric_state("sensor.goe_91234567_nrg_11") == pytest.approx(8.0 * 230.0 * 3)
    assert store.text_state("sensor.goe_91234567_car") == "2"  # charging


def test_wattpilot_frc_off_stops_charging_and_status_is_connected():
    package = load_archetype("fronius_de")
    store = package.build_store()
    status, _ = store.apply_service(
        "select", "select_option", {"entity_id": "select.goe_91234567_frc", "option": "1"}
    )
    assert status == 200
    state = _tick(package, store, _arrive("wattpilot"))
    assert state.evcs_power_w == 0.0
    assert store.text_state("sensor.goe_91234567_car") == "3"  # plugged, waiting
    store.apply_service(
        "select", "select_option", {"entity_id": "select.goe_91234567_frc", "option": "2"}
    )
    state = _tick(package, store, physics=state)
    assert state.evcs_power_w == pytest.approx(16.0 * 230.0 * 3)


def test_wattpilot_full_car_reports_complete():
    package = load_archetype("fronius_de")
    store = package.build_store()
    state = _tick(package, store, _arrive("wattpilot", soc_pct=100.0))
    assert state.evcs_power_w == 0.0
    assert store.text_state("sensor.goe_91234567_car") == "4"


def test_goe_one_phase_car_charges_on_one_phase():
    package = load_archetype("huawei_en")
    store = package.build_store()
    store.apply_service("number", "set_value", {"entity_id": "number.goe_204711_amp", "value": 32})
    state = _tick(package, store, _arrive("goe"))
    assert state.evcs_power_w == pytest.approx(32.0 * 230.0)
    assert store.numeric_state("sensor.goe_204711_nrg_11") == pytest.approx(32.0 * 230.0)


# --- KEBA read-only: ignores writes, kW sensor, energy counter ---------------------


def test_keba_read_only_charges_at_pair_maximum_with_kw_sensor_and_counter():
    package = load_archetype("sma_keba")
    store = package.build_store()
    assert wallbox_setpoints_from_store(store, package) == {}
    state = _tick(package, store, _arrive("keba"), n_ticks=4)
    power_kw = 16.0 * 230.0 * 3 / 1000.0
    assert state.evcs_power_w == pytest.approx(power_kw * 1000.0)
    assert store.numeric_state("sensor.keba_p30_charging_power") == pytest.approx(power_kw)
    assert store.numeric_state("sensor.keba_p30_total_energy") == pytest.approx(
        4567.8 + power_kw * 1.0, abs=1e-5
    )


# --- configuration checks ----------------------------------------------------------


def test_writable_wallbox_without_current_value_raises_when_car_charges():
    package = load_archetype("evcc_en")
    store = package.build_store()
    store.set_state("number.evcc_loadpoint_1_max_current", "unavailable")
    with pytest.raises(ValueError, match="no setpoints"):
        _tick(package, store, _arrive("lp1"))


def test_current_entity_must_be_in_ampere():
    base = load_archetype("evcc_en")
    entities = [dict(item) for item in base.entities]
    for item in entities:
        if item["entity_id"] == "number.evcc_loadpoint_1_max_current":
            item["attributes"] = {**item["attributes"], "unit_of_measurement": "W"}
    package = replace(base, entities=entities)
    with pytest.raises(ValueError, match="must be in A"):
        wallbox_setpoints_from_lookup(package, lambda _e: 16.0, lambda _e: "on")


@pytest.mark.parametrize(
    ("entities", "message"),
    [
        ({"max_current": "number.x", "colour": "sensor.y"}, "unknown keys"),
        ({"enable": "switch.x"}, "enable must be"),
        ({"enable": {"entity_id": "switch.x", "off_states": []}}, "off_states"),
        ({"status": {"entity_id": "sensor.x", "states": {"none": "1"}}}, "needs exactly"),
        ({"power": "not_an_entity"}, "is no entity id"),
    ],
)
def test_wallbox_entities_are_validated(entities, message):
    params = {
        "wallboxes": [
            {"id": "lp1", "voltage_v": 230, "phases": 3, "min_current_a": 6,
             "max_current_a": 16, "entities": entities}
        ]
    }
    with pytest.raises(ValueError, match=message):
        parse_wallboxes(params)


def test_read_only_wallbox_rejects_setpoint_entities():
    params = {
        "wallboxes": [
            {"id": "keba", "voltage_v": 230, "phases": 3, "min_current_a": 6,
             "max_current_a": 16, "read_only": True,
             "entities": {"max_current": "number.keba_current"}}
        ]
    }
    with pytest.raises(ValueError, match="read_only"):
        parse_wallboxes(params)


# --- S4 persistence helper ---------------------------------------------------------


def test_evcs_state_round_trip_and_mismatch():
    package = load_archetype("evcc_en")
    store = package.build_store()
    state = _tick(package, store, _arrive("lp1"))
    params = package.house_params
    wallboxes, evs = parse_wallboxes(params), parse_evs(params)
    restored = evcs_state_from_dict(state.evcs.as_dict(), wallboxes=wallboxes, evs=evs)
    assert restored.ev_at_wallbox == {"lp1": "car_a"}
    assert restored.ev_soc_pct == state.evcs.ev_soc_pct
    assert restored.wallbox_power_w == {"lp1": 0.0}
    bad = EvcsState(ev_at_wallbox={"lp9": "car_a"}, ev_soc_pct={"car_a": 50.0}).as_dict()
    with pytest.raises(ValueError, match="do not match"):
        evcs_state_from_dict(bad, wallboxes=wallboxes, evs=evs)


def test_initial_physics_reads_wallbox_energy_counter_from_fixture():
    package = load_archetype("sma_keba")
    assert initial_physics(package).evcs.wallbox_energy_kwh == {"keba": pytest.approx(4567.8)}
