"""Tests für Thermals P1a — Haus-Wärme MILP flex bridge."""
from __future__ import annotations

from datetime import date, datetime, time

import pytest

from house_config.planning_flex_bridge import (
    collect_planning_flex_consumers,
    house_profile_baseload_overlay,
    planning_thermal_daily_targets,
    planning_thermal_to_milp,
    thermal_optimizer_flex_enabled,
)
from optimizer.thermal_flex_context import (
    resolve_thermal_flex_contexts,
    thermal_daily_kwh_for_date,
)


def _wp_consumer() -> dict:
    return {
        "id": "wp_heating",
        "legacy_id": "waermepumpe",
        "label": "Wärmepumpe",
        "type": "thermal_annual",
        "nominal_power_kw": 1.6,
        "living_area_m2": 157.0,
        "building_class": 2,
        "heat_pump_type": "erde",
        "persons": 2,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        "loxone_inputs": {"power_name": "Ernie_WP_P_act"},
        "loxone_outputs": {"enable_name": "Ernie_WP_Freigabe"},
    }


def _house_profile() -> dict:
    return {
        "id": "example_efh",
        "latitude": 47.4,
        "longitude": 9.7,
        "annual_kwh": 11000.0,
        "consumers": [_wp_consumer()],
    }


def test_thermal_optimizer_flex_enabled_defaults():
    consumer = _wp_consumer()
    assert thermal_optimizer_flex_enabled(consumer) is True
    consumer["optimizer_flex"] = False
    assert thermal_optimizer_flex_enabled(consumer) is False


def test_planning_thermal_to_milp_bridge():
    milp = planning_thermal_to_milp(_wp_consumer())
    assert milp["id"] == "wp_heating"
    assert milp["name"] == "Haus Wärme"
    assert milp["legacy_id"] == "waermepumpe"
    assert milp["daily_target_source"] == "thermal_annual"
    assert milp["signal_type"] == "binary"
    assert milp["min_on_quarterhours"] == 4
    assert milp["max_on_quarterhours"] == 16
    assert milp["loxone_outputs"]["enable_name"] == "Ernie_WP_Freigabe"
    assert milp["loxone_inputs"]["power_name"] == "Ernie_WP_P_act"


def test_planning_thermal_to_milp_without_loxone_stays_empty():
    consumer = _wp_consumer()
    del consumer["loxone_inputs"]
    del consumer["loxone_outputs"]
    milp = planning_thermal_to_milp(consumer)
    assert milp["loxone_outputs"] == {}
    assert milp["loxone_inputs"] == {}


def test_collect_planning_flex_includes_wp_heating():
    flex = collect_planning_flex_consumers(_house_profile())
    ids = {entry["id"] for entry in flex}
    assert "wp_heating" in ids


def test_overlay_skips_milp_flex_thermal():
    profile = _house_profile()
    slots = [datetime(2024, 1, 15, h, 0) for h in range(24)]
    with_overlay = house_profile_baseload_overlay(
        profile,
        slots,
        milp_flex_thermal_ids=set(),
    )
    without_overlay = house_profile_baseload_overlay(
        profile,
        slots,
        milp_flex_thermal_ids={"wp_heating"},
    )
    assert sum(with_overlay) > sum(without_overlay)


def test_planning_thermal_daily_targets_matches_single_calendar_day(monkeypatch):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    profile = _house_profile()
    milp = planning_thermal_to_milp(_wp_consumer())
    slots = [datetime(2024, 1, 15, h, 0) for h in range(24)]
    from data.modeled_climate import ModeledClimateContext

    climate = ModeledClimateContext.for_house_profile(profile, kwp=0.0)
    targets = planning_thermal_daily_targets(
        [milp],
        profile,
        slots,
        climate=climate,
    )
    single_day = thermal_daily_kwh_for_date(
        _wp_consumer(),
        profile,
        date(2024, 1, 15),
        climate=climate,
    )
    assert targets["wp_heating"] == pytest.approx(round(single_day, 3), rel=1e-3)


def test_planning_thermal_daily_targets_cross_midnight_is_slot_energy(monkeypatch):
    """24h windows spanning two dates must not sum two full calendar days."""
    from datetime import timedelta

    from data.modeled_climate import ModeledClimateContext
    from house_config.planning_flex_bridge import _consumer_window_kwh
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    profile = _house_profile()
    milp = planning_thermal_to_milp(_wp_consumer())
    window_end = datetime(2025, 3, 1, 12, 0)
    slots = [window_end - timedelta(hours=24 - i) for i in range(24)]
    climate = ModeledClimateContext.for_house_profile(profile, kwp=0.0)
    targets = planning_thermal_daily_targets(
        [milp],
        profile,
        slots,
        climate=climate,
    )
    expected = _consumer_window_kwh(_wp_consumer(), slots, climate=climate)
    assert targets["wp_heating"] == pytest.approx(expected, rel=1e-6)
    dates = {slot.date() for slot in slots}
    assert len(dates) == 2
    full_days = sum(
        thermal_daily_kwh_for_date(_wp_consumer(), profile, day, climate=climate)
        for day in dates
    )
    assert expected < full_days * 0.75


def test_prorate_thermal_day_target_scales_partial_days():
    from optimizer.thermal_flex_context import (
        _max_on_slots_with_limits,
        _prorate_thermal_day_target_kwh,
    )

    assert _prorate_thermal_day_target_kwh(14.14, 24) == pytest.approx(14.14)
    assert _prorate_thermal_day_target_kwh(14.14, 17) == pytest.approx(
        round(14.14 * 17 / 24, 3)
    )
    assert _prorate_thermal_day_target_kwh(14.751, 7) == pytest.approx(
        round(14.751 * 7 / 24, 3)
    )
    # 7 slots, max consecutive 4: cannot turn all 7 ON
    assert _max_on_slots_with_limits(7, max_hours=4, max_pulses=4) < 7


def test_thermal_milp_cross_midnight_window_is_feasible(monkeypatch):
    """Partial calendar days in a 07:00 window must not make MILP Infeasible."""
    from datetime import timedelta

    from data.modeled_climate import ModeledClimateContext
    from optimizer.cbc_solver import solve_with_strict_fallback
    from optimizer.milp import _add_milp_objective
    from optimizer.milp_consumers import filter_feasible_consumers
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.thermal_flex_context import add_thermal_flex_constraints
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    profile = _house_profile()
    consumer = planning_thermal_to_milp(_wp_consumer())
    anchor = datetime(2025, 3, 1, 7, 0)
    matrix = []
    for offset in range(24):
        slot = anchor - timedelta(hours=24 - offset)
        matrix.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "k_act": 10.0,
                "price_buy": 0.10,
                "expected_p_act": 0.5,
                "expected_p_pv": 0.0,
                "consumption_mode": "profile_spec",
            }
        )
    climate = ModeledClimateContext.for_house_profile(profile, kwp=0.0)
    contexts = resolve_thermal_flex_contexts(
        matrix, [consumer], profile, climate=climate
    )
    assert len(contexts[consumer["id"]]["daily_targets"]) == 2
    remaining = {consumer["id"]: 14.0}
    battery = {
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "battery_capacity_kwh": 10.0,
        "efficiency": 0.95,
    }
    planned = filter_feasible_consumers(
        [consumer], remaining, matrix, list(range(24)), False, {}, {}
    )
    model = _build_milp_model(
        matrix, 24, battery, 50.0, planned, 0.0, remaining, {}
    )
    _add_milp_objective(model, matrix, 3.5, {}, wear_cent_per_kwh=0.0)
    add_thermal_flex_constraints(model, matrix, list(range(24)), contexts)
    assert solve_with_strict_fallback(model.prob, msg=False) == "Optimal"


def test_thermal_milp_chooses_cheaper_hours():
    import pulp

    from optimizer.cbc_solver import solve_with_strict_fallback
    from optimizer.milp import _add_milp_objective
    from optimizer.milp_consumers import _add_consumer_delivery_constraints, filter_feasible_consumers
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.thermal_flex_context import add_thermal_flex_constraints

    profile = _house_profile()
    consumer = planning_thermal_to_milp(_wp_consumer())
    day = date(2024, 1, 15)
    matrix = []
    for hour in range(24):
        price = 40.0 if 8 <= hour <= 20 else 10.0
        matrix.append(
            {
                "hour": hour,
                "date": day,
                "slot_datetime": datetime.combine(day, time(hour, 0)),
                "k_act": price,
                "price_buy": price / 100.0,
                "expected_p_act": 0.5,
                "expected_p_pv": 0.0,
                "consumption_mode": "profile_spec",
            }
        )
    contexts = resolve_thermal_flex_contexts(matrix, [consumer], profile)
    target_kwh = next(iter(contexts["wp_heating"]["daily_targets"].values()))
    remaining = {consumer["id"]: target_kwh}
    battery = {
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "battery_capacity_kwh": 10.0,
        "efficiency": 0.95,
    }
    planned = filter_feasible_consumers(
        [consumer],
        remaining,
        matrix,
        list(range(24)),
        False,
        {},
        {},
    )
    model = _build_milp_model(
        matrix,
        24,
        battery,
        50.0,
        planned,
        0.0,
        remaining,
        {},
    )
    _add_milp_objective(model, matrix, 3.5, {}, wear_cent_per_kwh=0.0)
    _add_consumer_delivery_constraints(
        model,
        matrix,
        remaining,
        list(range(24)),
        {},
        False,
    )
    add_thermal_flex_constraints(
        model,
        matrix,
        list(range(24)),
        contexts,
    )
    assert solve_with_strict_fallback(model.prob, msg=False) == "Optimal"
    on = model.consumer_on["wp_heating"]
    on_hours = [hour for hour, var in enumerate(on) if var.varValue and var.varValue > 0.5]
    assert on_hours
    assert all(hour < 8 or hour > 20 for hour in on_hours)
    pulse_lengths: list[int] = []
    index = 0
    while index < len(on):
        if on[index].varValue and on[index].varValue > 0.5:
            start = index
            while index < len(on) and on[index].varValue and on[index].varValue > 0.5:
                index += 1
            pulse_lengths.append(index - start)
        else:
            index += 1
    assert all(1 <= length <= 4 for length in pulse_lengths)
    nominal = consumer["nominal_power_kw"]
    for hour, var in enumerate(on):
        if var.varValue and var.varValue > 0.5:
            assert model.consumer_milp_charge_kw["wp_heating"] == pytest.approx(nominal)
        else:
            assert var.varValue is not None and var.varValue <= 0.5
