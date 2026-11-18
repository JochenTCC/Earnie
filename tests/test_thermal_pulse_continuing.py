"""The already-running flag (continue_on) exempts only the first day's first block from the pulse count."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pulp

from house_config.planning_flex_bridge import planning_thermal_to_milp
from optimizer.milp import _add_milp_objective
from optimizer.milp_horizon import _build_milp_model
from optimizer.thermal_flex_context import add_thermal_flex_constraints

SLOTS_PER_DAY = 4
DAY1 = date(2024, 1, 15)
DAY2 = DAY1 + timedelta(days=1)


def _consumer() -> dict:
    consumer = planning_thermal_to_milp(
        {
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
        }
    )
    consumer["max_pulses_per_day"] = 1
    consumer["max_on_quarterhours"] = SLOTS_PER_DAY
    return consumer


def _matrix() -> list[dict]:
    rows = []
    for day in (DAY1, DAY2):
        for hour in range(SLOTS_PER_DAY):
            rows.append(
                {
                    "hour": hour,
                    "date": day,
                    "slot_datetime": datetime.combine(day, time(hour, 0)),
                    "k_act": 10.0,
                    "price_buy": 0.10,
                    "expected_p_act": 0.5,
                    "expected_p_pv": 0.0,
                    "consumption_mode": "profile_spec",
                }
            )
    return rows


def _status_with_two_blocks_on(day_offset: int) -> str:
    """Pin ON-OFF-ON on one day while the device is already running at the plan start."""
    consumer = _consumer()
    matrix = _matrix()
    horizon = len(matrix)
    battery = {
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "battery_capacity_kwh": 10.0,
        "efficiency": 0.95,
    }
    remaining = {consumer["id"]: 100.0}
    model = _build_milp_model(matrix, horizon, battery, 50.0, [consumer], 0.0, remaining, {})
    _add_milp_objective(model, matrix, 3.5, {}, wear_cent_per_kwh=0.0)
    contexts = {consumer["id"]: {"daily_targets": {DAY1: 0.1, DAY2: 0.1}}}
    add_thermal_flex_constraints(
        model,
        matrix,
        list(range(horizon)),
        contexts,
        consumer_continue_on={consumer["id"]: True},
    )
    on = model.consumer_on[consumer["id"]]
    first = day_offset * SLOTS_PER_DAY
    model.prob += on[first] == 1
    model.prob += on[first + 1] == 0
    model.prob += on[first + 2] == 1
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    return pulp.LpStatus[model.prob.status]


def test_continuing_block_on_first_day_is_not_a_new_pulse():
    # Running at plan start: the first block continues, only the second one is a start.
    assert _status_with_two_blocks_on(day_offset=0) == "Optimal"


def test_continuing_flag_does_not_free_a_pulse_on_later_days():
    # Day 2 starts a new block at its first slot; with 1 pulse/day, two blocks are infeasible.
    assert _status_with_two_blocks_on(day_offset=1) == "Infeasible"
