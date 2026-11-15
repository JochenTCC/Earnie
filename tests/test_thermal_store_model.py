"""HeatControl P4: one store level inside the MILP for Live and the SE (design § 8.6)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pulp
import pytest

from house_sim.core.heat_pump import HeatPumpStoreParams, HeatPumpStoreState, step_heat_pump_store
from optimizer.thermal_live_store import LiveStorePlan
from optimizer.thermal_model import ThermalBand
from optimizer.thermal_store_model import StoreLevelModel, add_store_level

# --- the module on a toy problem ------------------------------------------------------


def _toy(prices: list[float], store: StoreLevelModel, max_heat_kwh: float = 10.0):
    """Buy heat per slot at ``prices`` (efficiency 1), keep the store in its band."""
    prob = pulp.LpProblem("toy", pulp.LpMinimize)
    heat = [pulp.LpVariable(f"heat_{t}", 0.0, max_heat_kwh) for t in range(len(prices))]
    prob += pulp.lpSum(p * h for p, h in zip(prices, heat))
    model = SimpleNamespace(prob=prob)
    level = add_store_level(model, "s", store, list(range(len(prices))), lambda t: heat[t])
    assert prob.solve(pulp.PULP_CBC_CMD(msg=0)) == pulp.LpStatusOptimal
    return [h.varValue or 0.0 for h in heat], level


def _store(n: int, **kw) -> StoreLevelModel:
    base = dict(capacity_kwh=50.0, start_kwh=0.0, efficiency=1.0, drain_kwh=[0.0] * n)
    return StoreLevelModel(**{**base, **kw})


def test_the_level_follows_heat_drain_and_leak():
    drain = [1.0, 1.0, 1.0]
    heat, level = _toy([1.0] * 3, _store(3, start_kwh=10.0, drain_kwh=drain, leak_per_slot=0.1))
    assert heat == [0.0, 0.0, 0.0]
    expected = 10.0
    for slot in range(3):
        expected = 0.9 * expected - 1.0
        assert level.level_kwh(slot) == pytest.approx(expected)
    assert level.slack_kwh() == pytest.approx(0.0)


def test_losses_shorten_the_look_ahead():
    """Done criterion of P4: cheap heat far ahead pays only when the store holds it."""
    prices = [10.0] + [30.0] * 47
    drain = [0.0] * 47 + [5.0]
    tight, _ = _toy(prices, _store(48, drain_kwh=drain))
    leaky, _ = _toy(prices, _store(48, drain_kwh=drain, leak_per_slot=0.03))
    assert tight[0] == pytest.approx(5.0)  # loss-free: buy it all in the cheap slot
    assert leaky[0] == pytest.approx(0.0)  # 3 %/slot over 47 slots costs more than the spread
    assert sum(leaky[1:]) == pytest.approx(5.0, abs=1e-6)


def test_a_start_above_the_band_costs_no_slack():
    _heat, level = _toy([1.0] * 4, _store(4, capacity_kwh=5.0, start_kwh=8.0, leak_per_slot=0.05))
    assert level.slack_kwh() == pytest.approx(0.0)
    assert level.level_kwh(3) == pytest.approx(8.0 * 0.95**4)


def test_collector_surplus_on_a_full_store_is_spilled_for_free():
    store = _store(3, capacity_kwh=5.0, start_kwh=5.0, drain_kwh=[-2.0] * 3, spill_max_kwh=[2.0] * 3)
    _heat, level = _toy([1.0] * 3, store)
    assert level.slack_kwh() == pytest.approx(0.0)


def test_the_terminal_level_is_held_at_the_end():
    heat, level = _toy([5.0, 1.0, 9.0], _store(3, terminal_min_kwh=4.0))
    assert level.level_kwh(2) == pytest.approx(4.0)
    assert heat == [pytest.approx(0.0), pytest.approx(4.0), pytest.approx(0.0)]


def test_band_slack_only_when_the_power_is_too_small():
    _heat, level = _toy([1.0] * 2, _store(2, drain_kwh=[3.0, 3.0]), max_heat_kwh=1.0)
    assert level.slack_kwh() == pytest.approx(4.0)


def test_invalid_parameters_fail_loud():
    with pytest.raises(ValueError, match="Speicherverlust"):
        _store(1, leak_per_slot=1.0)
    with pytest.raises(ValueError, match="Wirkungsgrad"):
        _store(1, efficiency=0.0)


# --- Live MILP ------------------------------------------------------------------------

_DAY = date(2026, 11, 16)
_CID = "wp_heating"
_CHEAP_HOURS = range(2, 6)
_C = 2.0  # kWh/K
_BAND = ThermalBand(47.0, 5.0)  # band minimum 42 °C
_BOOST = 10.0  # charge maximum 57 °C
_DRAW_KW = 1.0
_JAZ = 4.0
_WP_KW = 1.9


def _source() -> dict:
    return {
        "id": _CID,
        "label": "Wärmepumpe",
        "type": "thermal_annual",
        "nominal_power_kw": _WP_KW,
        "daily_target_source": "thermal_annual",
        "thermal": {
            "heat_source": {"type": "heat_pump", "heat_pump_type": "erde"},
            "heat_storage": {"volume_liters": 887.0, "setpoint_c": 47.0, "tolerance_c": 5.0},
        },
    }


def _matrix(hours: int = 24) -> list[dict]:
    start = datetime.combine(_DAY, time(0, 0))
    rows = []
    for index in range(hours * 4):
        slot = start + timedelta(minutes=15 * index)
        price = 5.0 if slot.hour in _CHEAP_HOURS else 40.0
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "k_act": price,
                "price_buy": price / 100.0,
                "expected_p_act": 0.0,
                "expected_p_pv": 0.0,
                "consumption_mode": "live_snapshot",
            }
        )
    return rows


def _plan(start_c: float, hours: int = 24) -> LiveStorePlan:
    return LiveStorePlan(
        forced_hour_flags=[False] * hours,
        floor_electric_kwh=0.0,
        opp_cap_electric_kwh=0.0,
        start_temp_c=start_c,
        temp_low_c=None,
        used_measured_eq=True,
        used_measured_low=False,
        band=_BAND,
        electric_by_hour=[0.0] * hours,
        store_temp_c=[44.0] * hours,  # normal operation hovers around 44 °C
        boost_k=_BOOST,
        capacity_kwh_per_k=_C,
        heat_loss_kw_per_k=0.0,
        jaz=_JAZ,
        ambient_c=[5.0] * hours,
        draw_kw_by_hour=[_DRAW_KW] * hours,
    )


def _solve_live(plan: LiveStorePlan):
    from house_config.planning_flex_bridge import planning_thermal_to_milp
    from optimizer.cbc_solver import solve_with_strict_fallback
    from optimizer.milp import _add_milp_objective
    from optimizer.milp_consumers import filter_feasible_consumers
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.thermal_flex_context import LIVE_STORE_PLAN_KEY, add_thermal_flex_constraints

    consumer = planning_thermal_to_milp(_source())
    matrix = _matrix()
    n = len(matrix)
    contexts = {_CID: {"forced_indices": [], LIVE_STORE_PLAN_KEY: plan}}
    remaining = {_CID: max(plan.charge_room_electric_kwh, 1e-3)}
    battery = {
        "min_soc": 10.0,
        "max_soc": 10.0001,
        "max_power_kw": 0.001,
        "battery_capacity_kwh": 0.01,
        "efficiency": 0.95,
    }
    planned = filter_feasible_consumers([consumer], remaining, matrix, list(range(n)), False, {}, {})
    model = _build_milp_model(matrix, n, battery, 10.0, planned, 0.0, remaining, {})
    _add_milp_objective(model, matrix, 0.0, {}, wear_cent_per_kwh=0.0)
    add_thermal_flex_constraints(model, matrix, list(range(n)), contexts)
    model.live_store_plans = {_CID: plan}
    assert solve_with_strict_fallback(model.prob, msg=False) == "Optimal"
    return model, matrix


def _power(model, slot: int) -> float:
    from optimizer.milp_consumer_vars import _consumer_power_at

    return float(_consumer_power_at(model, model.planned_consumers[0], slot))


def test_live_charges_the_store_in_the_cheap_hours():
    model, matrix = _solve_live(_plan(44.0))
    store, levels = model.live_store_levels[_CID]
    run_slots = [t for t in range(len(matrix)) if _power(model, t) > 1e-3]
    assert run_slots
    assert all(matrix[t]["slot_datetime"].hour in _CHEAP_HOURS for t in run_slots)
    assert levels.slack_kwh() == pytest.approx(0.0, abs=1e-6)
    # The last slot holds at least the mean level of normal operation (44 °C).
    assert levels.level_kwh(len(matrix) - 1) >= store.terminal_min_kwh - 1e-6
    assert store.terminal_min_kwh == pytest.approx(_C * 2.0)


def test_live_leaves_a_hot_store_alone():
    hot = _plan(57.0)
    model, matrix = _solve_live(LiveStorePlan(**{**hot.__dict__, "draw_kw_by_hour": [0.05] * 24}))
    assert all(_power(model, t) <= 1e-3 for t in range(len(matrix)))


def test_the_target_is_the_planned_level_at_the_end_of_the_run():
    from optimizer.heat_storage_target import heat_storage_targets, store_level_report

    plan = _plan(42.5)
    model, _matrix_rows = _solve_live(plan)
    targets = heat_storage_targets(model)
    report = store_level_report(model)[_CID]
    assert report["band_slack_kwh"] == pytest.approx(0.0, abs=1e-3)
    assert len(report["planned_temp_c"]) == 96
    if _power(model, 0) > 1e-3:
        assert _BAND.setpoint_c <= targets[_CID] <= plan.charge_max_c
    else:
        assert targets[_CID] == 0.0


def test_the_partial_last_hour_uses_the_last_plan_hour_and_beyond_fails_loud():
    from optimizer.thermal_live_store import _slot_hours

    matrix = _matrix(3)[:9]  # 2 h 15 min: the plan has floor(9 × 0.25) = 2 hours
    assert _slot_hours(matrix, 2) == [0] * 4 + [1] * 4 + [1]
    with pytest.raises(ValueError, match="reicht nur 1 h"):
        _slot_hours(matrix, 1)


# --- closed loop with the HouseSim controller -----------------------------------------


def test_house_sim_follows_the_plan_through_the_target():
    """The plan drives the controller through the target alone; the store stays in its band
    and every planned charge ends at its target."""
    plan = _plan(44.0)
    model, matrix = _solve_live(plan)
    _store, levels = model.live_store_levels[_CID]
    n = len(matrix)
    on = [_power(model, t) > 1e-3 for t in range(n)]
    targets: list[float] = []
    for t in range(n):
        if not on[t]:
            targets.append(0.0)
            continue
        end = t
        while end + 1 < n and on[end + 1]:
            end += 1
        temp = _BAND.min_c + levels.level_kwh(end) / _C
        targets.append(round(min(max(temp, _BAND.setpoint_c), plan.charge_max_c), 1))
    params = HeatPumpStoreParams(
        capacity_kwh_per_k=_C, heat_loss_kw_per_k=0.0, heat_power_kw=_WP_KW * _JAZ, cop=_JAZ,
        setpoint_c=_BAND.setpoint_c, tolerance_c=_BAND.tolerance_c, boost_k=_BOOST,
        max_c=plan.charge_max_c,
    )
    state = HeatPumpStoreState(temp_c=44.0)
    temps: list[float] = []
    for t in range(n):
        state, _kwh = step_heat_pump_store(
            params, state, demand_kw=_DRAW_KW, ambient_c=5.0, dt_h=0.25, store_target_c=targets[t]
        )
        temps.append(state.temp_c)
    assert min(temps) >= _BAND.min_c - 0.5
    assert max(temps) <= plan.charge_max_c + 1e-6
    run_ends = [t for t in range(n) if on[t] and (t + 1 == n or not on[t + 1])]
    assert run_ends
    for end in run_ends:
        assert temps[end] == pytest.approx(targets[end], abs=0.5)
