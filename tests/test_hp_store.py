"""SE: the heat pump's band (optimizer.hp_store) limits how far the MILP shifts its heat."""
from __future__ import annotations

from datetime import date, datetime, time

import pulp
import pytest

from house_config.planning_flex_bridge import planning_thermal_to_milp
from optimizer.hp_store import (
    HP_STORE_CONTEXT_KEY,
    HP_STORE_START_KEY,
    hp_store_balance,
    hp_store_capacity,
    next_hp_level_kwh,
)
from optimizer.thermal_flex_context import resolve_thermal_flex_contexts
from optimizer.thermal_house import house_capacity_kwh_per_k
from optimizer.thermal_model import capacity_kwh_per_k_from_volume

_DAY = date(2024, 1, 15)


def _pump(**extra) -> dict:
    return {
        "id": "wp_heating",
        "label": "Wärmepumpe",
        "type": "thermal_annual",
        "nominal_power_kw": 1.6,
        "living_area_m2": 157.0,
        "building_class": 2,
        "heat_source": {"type": "heat_pump", "heat_pump_type": "erde"},
        "persons": 2,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        **extra,
    }


def _profile(pump: dict) -> dict:
    return {
        "id": "example_efh",
        "latitude": 47.4,
        "longitude": 9.7,
        "annual_kwh": 11000.0,
        "consumers": [pump],
    }


def _matrix(dear_from: int = 8, dear_to: int = 20) -> list[dict]:
    rows = []
    for hour in range(24):
        price = 40.0 if dear_from <= hour <= dear_to else 10.0
        rows.append(
            {
                "hour": hour,
                "date": _DAY,
                "slot_datetime": datetime.combine(_DAY, time(hour, 0)),
                "k_act": price,
                "price_buy": price / 100.0,
                "expected_p_act": 0.5,
                "expected_p_pv": 0.0,
                "consumption_mode": "profile_spec",
            }
        )
    return rows


def _solve(pump_source: dict):
    from optimizer.cbc_solver import solve_with_strict_fallback
    from optimizer.milp import _add_milp_objective
    from optimizer.milp_consumers import _add_consumer_delivery_constraints, filter_feasible_consumers
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.thermal_flex_context import add_thermal_flex_constraints

    profile = _profile(pump_source)
    consumer = planning_thermal_to_milp(_pump())
    matrix = _matrix()
    contexts = resolve_thermal_flex_contexts(matrix, [consumer], profile)
    target_kwh = next(iter(contexts["wp_heating"]["daily_targets"].values()))
    remaining = {consumer["id"]: target_kwh}
    battery = {
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 0.1,
        "battery_capacity_kwh": 0.1,
        "efficiency": 0.95,
    }
    planned = filter_feasible_consumers([consumer], remaining, matrix, list(range(24)), False, {}, {})
    model = _build_milp_model(matrix, 24, battery, 50.0, planned, 0.0, remaining, {})
    _add_milp_objective(model, matrix, 3.5, {}, wear_cent_per_kwh=0.0)
    _add_consumer_delivery_constraints(model, matrix, remaining, list(range(24)), {}, False)
    add_thermal_flex_constraints(model, matrix, list(range(24)), contexts)
    assert solve_with_strict_fallback(model.prob, msg=False) == "Optimal"
    on_hours = [
        hour for hour, var in enumerate(model.consumer_on["wp_heating"]) if (var.varValue or 0.0) > 0.5
    ]
    return model, contexts["wp_heating"], on_hours


# --- Capacity


def test_capacity_of_a_house_without_store_is_its_mass_times_the_comfort_band() -> None:
    capacity = hp_store_capacity(_pump(house_tolerance_c=0.5, building_mass="mittel"))

    assert capacity.store_kwh == 0.0
    assert capacity.house_kwh == pytest.approx(house_capacity_kwh_per_k(157.0, "mittel") * 0.5)


def test_a_store_adds_its_band_to_the_house() -> None:
    capacity = hp_store_capacity(
        _pump(house_tolerance_c=0.5, heat_storage={"volume_liters": 500.0, "tolerance_c": 5.0})
    )

    assert capacity.store_kwh == pytest.approx(capacity_kwh_per_k_from_volume(500.0) * 5.0)
    assert capacity.total_kwh == pytest.approx(capacity.store_kwh + capacity.house_kwh)
    assert capacity.total_kwh > hp_store_capacity(_pump(house_tolerance_c=0.5)).total_kwh


def test_no_store_and_no_living_area_fails_loud() -> None:
    with pytest.raises(ValueError, match="keine Speichergrenze"):
        hp_store_capacity(_pump(living_area_m2=0.0))


def test_a_window_starts_in_the_middle_of_the_band_or_at_the_carried_level() -> None:
    pump = _pump(house_tolerance_c=0.5)
    fresh = hp_store_balance("wp_heating", pump, [0.5] * 4, 4.0, start_levels_kwh=None)
    carried = hp_store_balance("wp_heating", pump, [0.5] * 4, 4.0, start_levels_kwh={"wp_heating": 1.0})

    assert fresh.start_kwh == pytest.approx(fresh.capacity_kwh / 2.0)
    assert carried.start_kwh == pytest.approx(1.0)
    assert fresh.drain_kwh == [pytest.approx(2.0)] * 4


def test_the_booked_level_stays_inside_the_band() -> None:
    assert next_hp_level_kwh(1.0, 5.0, 0.5, 3.0) == 3.0
    assert next_hp_level_kwh(1.0, 0.0, 2.0, 3.0) == 0.0
    assert next_hp_level_kwh(1.0, 1.0, 0.5, 3.0) == pytest.approx(1.5)


# --- Contexts


def test_the_se_context_carries_the_band_and_the_carried_level() -> None:
    pump = _pump()
    consumer = planning_thermal_to_milp(_pump())

    contexts = resolve_thermal_flex_contexts(
        _matrix(), [consumer], _profile(pump), hp_store_start_kwh={"wp_heating": 2.0}
    )

    balance = contexts["wp_heating"][HP_STORE_CONTEXT_KEY]
    assert balance.start_kwh == pytest.approx(min(2.0, balance.capacity_kwh))
    assert len(balance.drain_kwh) == 24


# --- MILP


def test_a_narrow_band_keeps_the_pump_running_in_dear_hours() -> None:
    """Without a store and with a thin comfort band the pump cannot move its day into cheap hours."""
    _model, _ctx, wide_on = _solve(
        _pump(heat_storage={"volume_liters": 5000.0, "tolerance_c": 20.0})
    )
    model, ctx, narrow_on = _solve(_pump(house_tolerance_c=0.05))

    assert all(hour < 8 or hour > 20 for hour in wide_on)
    assert any(8 <= hour <= 20 for hour in narrow_on)
    balance = ctx[HP_STORE_CONTEXT_KEY]
    for slot in range(24):
        level = pulp.value(model.prob.variablesDict()[f"wp_heating_hp_store_{slot}"])
        below, above = model.hp_store_slack["wp_heating"][slot]
        assert -1e-6 - (below.varValue or 0.0) <= level <= balance.capacity_kwh + (above.varValue or 0.0) + 1e-6


def test_slack_is_only_used_when_the_band_cannot_hold() -> None:
    model, _ctx, _on = _solve(_pump(house_tolerance_c=0.5))

    used = sum((b.varValue or 0.0) + (a.varValue or 0.0) for b, a in model.hp_store_slack["wp_heating"])
    assert used == pytest.approx(0.0, abs=1e-6)


# --- Carried level after a booked window


def test_levels_after_window_follow_the_booked_heat(monkeypatch) -> None:
    from types import SimpleNamespace

    from optimizer.hp_store import HpStoreBalance
    from optimizer.targets import consumer_column_name
    from simulation import anchor_step

    consumer = planning_thermal_to_milp(_pump())
    balance = HpStoreBalance(capacity_kwh=10.0, start_kwh=5.0, efficiency=4.0, drain_kwh=[1.0, 1.0])
    seen: list[dict] = []

    def fake_contexts(_matrix, _consumers, _override):
        from optimizer.scenario_planning_scope import planning_runtime_settings

        seen.append(planning_runtime_settings().get(HP_STORE_START_KEY))
        return {"wp_heating": {HP_STORE_CONTEXT_KEY: balance}}

    monkeypatch.setattr(anchor_step, "_resolve_thermal_flex_contexts", fake_contexts)
    column = consumer_column_name(consumer)
    rows = [{column: 2.0}, {column: 0.0}]  # kW: 0.5 kWh × JAZ 4 = 2 kWh heat, then none

    after = anchor_step.hp_store_levels_after_window(
        [SimpleNamespace()] * 2, rows, [consumer], {}, {"wp_heating": 5.0}
    )

    assert seen == [{"wp_heating": 5.0}]
    assert after == {"wp_heating": pytest.approx(5.0 + 2.0 - 1.0 - 1.0)}
