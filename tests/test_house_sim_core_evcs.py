"""HouseSim wallbox write-back W1: wallbox and EV physics in house_sim.core."""
from __future__ import annotations

from dataclasses import replace

import pytest

from house_sim.core.archetype import ArchetypePackage, load_archetype
from house_sim.core.evcs import (
    EvParams,
    WallboxParams,
    WallboxSetpoints,
    charge_power_w,
    parse_evs,
    parse_wallboxes,
)
from house_sim.core.physics import (
    EssSetpoints,
    ScenarioOverlay,
    initial_physics,
    step_physics,
)

BOX_3P = WallboxParams(
    id="lp1", voltage_v=230.0, phases=3, min_current_a=6.0, max_current_a=16.0
)
CAR_3P = EvParams(
    id="car_a", capacity_kwh=60.0, initial_soc_pct=40.0, max_charge_power_kw=11.0, phases=3
)


def _package(**params) -> ArchetypePackage:
    base = load_archetype("evcc_en")
    house_params = dict(base.house_params)
    house_params.pop("initial_evcs_power_w", None)
    house_params.update(params)
    return replace(base, house_params=house_params)


def _two_box_package(**extra) -> ArchetypePackage:
    return _package(
        wallboxes=[
            {"id": "lp1", "voltage_v": 230, "phases": 3, "min_current_a": 6, "max_current_a": 16},
            {"id": "lp2", "voltage_v": 230, "phases": 1, "min_current_a": 6, "max_current_a": 32},
        ],
        evs=[
            {"id": "car_a", "capacity_kwh": 60, "initial_soc_pct": 40,
             "max_charge_power_kw": 11, "phases": 3},
            {"id": "car_b", "capacity_kwh": 40, "initial_soc_pct": 80,
             "max_charge_power_kw": 7.4, "phases": 1},
        ],
        **extra,
    )


def _step(state, package, overlay=None, wallbox_setpoints=None, dt_h=0.25):
    return step_physics(
        state,
        package=package,
        setpoints=EssSetpoints(),
        dt_h=dt_h,
        overlay=overlay,
        wallbox_setpoints=wallbox_setpoints,
    )


# --- charge power -------------------------------------------------------------


def test_power_is_current_times_voltage_times_phases():
    power = charge_power_w(
        BOX_3P, CAR_3P, soc_pct=40.0, setpoints=WallboxSetpoints(10.0), dt_h=0.25
    )
    assert power == pytest.approx(10.0 * 230.0 * 3)


def test_one_phase_car_on_three_phase_box_charges_on_one_phase():
    car = replace(CAR_3P, phases=1)
    power = charge_power_w(BOX_3P, car, soc_pct=40.0, setpoints=WallboxSetpoints(16.0), dt_h=0.25)
    assert power == pytest.approx(16.0 * 230.0)


def test_current_below_minimum_gives_zero():
    power = charge_power_w(
        BOX_3P, CAR_3P, soc_pct=40.0, setpoints=WallboxSetpoints(5.9), dt_h=0.25
    )
    assert power == 0.0


def test_current_above_wallbox_maximum_is_capped():
    car = replace(CAR_3P, max_charge_power_kw=50.0)
    power = charge_power_w(BOX_3P, car, soc_pct=40.0, setpoints=WallboxSetpoints(32.0), dt_h=0.25)
    assert power == pytest.approx(16.0 * 230.0 * 3)


def test_car_acceptance_caps_power():
    car = replace(CAR_3P, max_charge_power_kw=7.0)
    power = charge_power_w(BOX_3P, car, soc_pct=40.0, setpoints=WallboxSetpoints(16.0), dt_h=0.25)
    assert power == pytest.approx(7000.0)


def test_disabled_wallbox_gives_zero():
    power = charge_power_w(
        BOX_3P, CAR_3P, soc_pct=40.0,
        setpoints=WallboxSetpoints(16.0, enabled=False), dt_h=0.25,
    )
    assert power == 0.0


def test_full_car_draws_no_more_than_remaining_energy():
    # 0.5 % of 60 kWh = 0.3 kWh left; in 0.25 h that is 1.2 kW at most.
    power = charge_power_w(
        BOX_3P, CAR_3P, soc_pct=99.5, setpoints=WallboxSetpoints(16.0), dt_h=0.25
    )
    assert power == pytest.approx(1200.0)
    assert charge_power_w(
        BOX_3P, CAR_3P, soc_pct=100.0, setpoints=WallboxSetpoints(16.0), dt_h=0.25
    ) == 0.0


def test_read_only_wallbox_charges_at_what_the_car_accepts():
    box = replace(BOX_3P, read_only=True)
    car = replace(CAR_3P, max_charge_power_kw=7.0)
    assert charge_power_w(box, car, soc_pct=40.0, setpoints=None, dt_h=0.25) == pytest.approx(7000.0)


def test_writable_wallbox_with_car_but_no_setpoints_raises():
    with pytest.raises(ValueError, match="no setpoints"):
        charge_power_w(BOX_3P, CAR_3P, soc_pct=40.0, setpoints=None, dt_h=0.25)


# --- parameters ---------------------------------------------------------------


def test_parse_rejects_missing_field_and_bad_phases():
    with pytest.raises(ValueError, match="voltage_v"):
        parse_wallboxes({"wallboxes": [{"id": "lp1", "phases": 3,
                                        "min_current_a": 6, "max_current_a": 16}]})
    with pytest.raises(ValueError, match="phases"):
        parse_evs({"evs": [{"id": "c", "capacity_kwh": 40, "initial_soc_pct": 50,
                            "max_charge_power_kw": 7, "phases": 4}]})


def test_parse_rejects_duplicate_ids():
    box = {"id": "lp1", "voltage_v": 230, "phases": 3, "min_current_a": 6, "max_current_a": 16}
    with pytest.raises(ValueError, match="Duplicate wallbox"):
        parse_wallboxes({"wallboxes": [box, dict(box)]})


def test_initial_evcs_power_is_rejected_with_wallbox_model():
    package = _two_box_package(initial_evcs_power_w=1000.0)
    with pytest.raises(ValueError, match="initial_evcs_power_w"):
        initial_physics(package)


def test_initial_ev_must_exist():
    package = _package(
        wallboxes=[{"id": "lp1", "voltage_v": 230, "phases": 3, "min_current_a": 6,
                    "max_current_a": 16, "initial_ev_id": "ghost"}],
        evs=[{"id": "car_a", "capacity_kwh": 60, "initial_soc_pct": 40,
              "max_charge_power_kw": 11, "phases": 3}],
    )
    with pytest.raises(ValueError, match="ghost"):
        initial_physics(package)


# --- step_physics -------------------------------------------------------------


def test_written_current_drives_grid_power_and_ev_soc():
    package = _two_box_package()
    state = initial_physics(package)
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    nxt = _step(state, package, overlay, {"lp1": WallboxSetpoints(10.0)})
    power_w = 10.0 * 230.0 * 3
    assert nxt.evcs_power_w == pytest.approx(power_w)
    assert nxt.evcs.wallbox_power_w == {"lp1": pytest.approx(power_w), "lp2": 0.0}
    # base load 1.5 kW + EV, PV tick 1 = 1.2 kW, ESS 0.
    assert nxt.grid_power_w == pytest.approx((1.5 + power_w / 1000.0 - 1.2) * 1000.0)
    expected_soc = 40.0 + power_w / 1000.0 * 0.25 / 60.0 * 100.0
    assert nxt.evcs.ev_soc_pct["car_a"] == pytest.approx(expected_soc)
    assert nxt.evcs.ev_soc_pct["car_b"] == pytest.approx(80.0)


def test_two_wallboxes_charge_two_cars_with_own_setpoints():
    package = _two_box_package()
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    overlay.car_arrives(wallbox="lp2", ev="car_b", soc_pct=20.0)
    nxt = _step(
        initial_physics(package), package, overlay,
        {"lp1": WallboxSetpoints(6.0), "lp2": WallboxSetpoints(32.0)},
    )
    assert nxt.evcs.wallbox_power_w["lp1"] == pytest.approx(6.0 * 230.0 * 3)
    # lp2: 32 A × 230 V × 1 phase = 7.36 kW, car_b accepts 7.4 kW.
    assert nxt.evcs.wallbox_power_w["lp2"] == pytest.approx(32.0 * 230.0)
    assert nxt.evcs.ev_soc_pct["car_b"] == pytest.approx(20.0 + 7.36 * 0.25 / 40.0 * 100.0)
    assert nxt.evcs_power_w == pytest.approx(6.0 * 230.0 * 3 + 32.0 * 230.0)


def test_unplug_stops_charging_and_keeps_soc():
    package = _two_box_package()
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    setpoints = {"lp1": WallboxSetpoints(16.0)}
    charged = _step(initial_physics(package), package, overlay, setpoints)
    overlay.car_leaves(wallbox="lp1")
    after = _step(charged, package, overlay, setpoints)
    assert after.evcs_power_w == 0.0
    assert "lp1" not in after.evcs.ev_at_wallbox
    assert after.evcs.ev_soc_pct["car_a"] == pytest.approx(charged.evcs.ev_soc_pct["car_a"])


def test_car_moves_to_another_wallbox_after_unplug():
    package = _two_box_package()
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    state = _step(initial_physics(package), package, overlay, {"lp1": WallboxSetpoints(16.0)})
    overlay.car_leaves(wallbox="lp1")
    overlay.car_arrives(wallbox="lp2", ev="car_a")
    moved = _step(state, package, overlay, {"lp2": WallboxSetpoints(16.0)})
    assert moved.evcs.ev_at_wallbox == {"lp2": "car_a"}
    assert moved.evcs.wallbox_of_ev("car_a") == "lp2"
    assert moved.evcs.wallbox_power_w["lp2"] == pytest.approx(16.0 * 230.0)


def test_plugging_one_car_into_two_wallboxes_raises():
    package = _two_box_package()
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    overlay.car_arrives(wallbox="lp2", ev="car_a")
    with pytest.raises(ValueError, match="already plugged"):
        _step(initial_physics(package), package, overlay, {})


def test_occupied_wallbox_raises():
    package = _two_box_package()
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    overlay.car_arrives(wallbox="lp1", ev="car_b")
    with pytest.raises(ValueError, match="already has EV"):
        _step(initial_physics(package), package, overlay, {})


def test_unknown_wallbox_raises():
    package = _two_box_package()
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp9", ev="car_a")
    with pytest.raises(ValueError, match="Unknown wallbox"):
        _step(initial_physics(package), package, overlay, {})


def test_fixed_power_override_is_rejected_with_wallbox_model():
    package = _two_box_package()
    overlay = ScenarioOverlay()
    overlay.car_arrives(7000.0)
    with pytest.raises(ValueError, match="car_arrives\\(wallbox="):
        _step(initial_physics(package), package, overlay)


def test_wallbox_event_without_wallbox_model_raises():
    package = load_archetype("evcc_en")
    overlay = ScenarioOverlay()
    overlay.car_arrives(wallbox="lp1", ev="car_a")
    with pytest.raises(ValueError, match="house_params.wallboxes"):
        _step(initial_physics(package), package, overlay)


def test_car_arrives_needs_both_wallbox_and_ev():
    with pytest.raises(ValueError, match="both"):
        ScenarioOverlay().car_arrives(wallbox="lp1")


def test_initial_ev_charges_from_first_tick_and_as_dict_carries_state():
    package = _package(
        wallboxes=[{"id": "lp1", "voltage_v": 230, "phases": 3, "min_current_a": 6,
                    "max_current_a": 16, "initial_ev_id": "car_a"}],
        evs=[{"id": "car_a", "capacity_kwh": 60, "initial_soc_pct": 40,
              "max_charge_power_kw": 11, "phases": 3}],
    )
    state = initial_physics(package)
    assert state.evcs.ev_at_wallbox == {"lp1": "car_a"}
    nxt = _step(state, package, None, {"lp1": WallboxSetpoints(16.0)})
    assert nxt.evcs_power_w == pytest.approx(11000.0)
    doc = nxt.as_dict()
    assert doc["evcs_power_w"] == pytest.approx(11000.0)
    assert doc["evcs"]["ev_at_wallbox"] == {"lp1": "car_a"}


def test_archetype_without_wallbox_model_keeps_state_without_evcs_key():
    package = load_archetype("evcc_en")
    state = initial_physics(package)
    assert "evcs" not in state.as_dict()
