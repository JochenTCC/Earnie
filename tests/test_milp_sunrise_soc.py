"""Tests für SOC_min-Randbedingung am Sonnenaufgang-Slot."""
from __future__ import annotations

import pulp

from optimizer.milp import (
    _add_milp_objective,
    _add_sunrise_soc_min_constraint,
    _build_milp_model,
)


def _price_matrix(hours: int, cheap_first: bool = True) -> list[dict]:
    prices = [10.0, 40.0] if cheap_first else [40.0, 10.0]
    return [
        {
            "hour": h,
            "expected_p_pv": 4.0 if h < 12 else 0.0,
            "expected_p_act": 1.0,
            "k_act": prices[0 if h < hours // 2 else 1],
            "expected_flex_kw": {},
        }
        for h in range(hours)
    ]


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.95,
    }


def test_sunrise_soc_min_constraint_holds():
    start_soc = 70.0
    battery_params = _battery_params()
    matrix = _price_matrix(hours=30)
    sunrise_index = 16
    model = _build_milp_model(
        matrix, 30, battery_params, start_soc, [], 0.0, {}, None
    )
    _add_milp_objective(model, matrix, 3.5, None, wear_cent_per_kwh=0.0)
    e_min = (battery_params["min_soc"] / 100.0) * battery_params["battery_capacity_kwh"]
    _add_sunrise_soc_min_constraint(model, sunrise_index, e_min)

    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"

    sunrise_energy = model.e_batt[sunrise_index].varValue
    end_energy = model.e_batt[-1].varValue
    e_start = (start_soc / 100.0) * battery_params["battery_capacity_kwh"]
    assert sunrise_energy is not None
    assert end_energy is not None
    assert abs(sunrise_energy - e_min) < 1e-4
    assert abs(end_energy - e_start) > 0.05
