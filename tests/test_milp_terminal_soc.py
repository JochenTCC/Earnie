"""Tests für die MILP-Randbedingung End-SOC = Start-SOC."""
from __future__ import annotations

import pulp

from optimizer.milp import (
    _add_milp_objective,
    _add_terminal_soc_constraint,
    _build_milp_model,
)


def _price_matrix(hours: int = 24, cheap_first: bool = True) -> list[dict]:
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


def _battery_params(end_soc_equals_start: bool) -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.95,
        "end_soc_equals_start": end_soc_equals_start,
    }


def test_terminal_soc_constraint_holds_in_solved_model():
    start_soc = 60.0
    battery_params = _battery_params(end_soc_equals_start=True)
    matrix = _price_matrix()
    model = _build_milp_model(matrix, 24, battery_params, start_soc, [])
    _add_milp_objective(model, matrix, 3.5)
    e_init = (start_soc / 100.0) * battery_params["battery_capacity_kwh"]
    _add_terminal_soc_constraint(model, e_init)

    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"

    end_energy = model.e_batt[-1].varValue
    assert end_energy is not None
    assert abs(end_energy - e_init) < 1e-4


def test_without_constraint_end_soc_can_differ_from_start():
    start_soc = 60.0
    battery_params = _battery_params(end_soc_equals_start=False)
    matrix = _price_matrix()
    model = _build_milp_model(matrix, 24, battery_params, start_soc, [])
    _add_milp_objective(model, matrix, 3.5)

    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"

    e_init = (start_soc / 100.0) * battery_params["battery_capacity_kwh"]
    end_energy = model.e_batt[-1].varValue
    assert end_energy is not None
    assert abs(end_energy - e_init) > 0.05


def test_terminal_soc_uses_anchor_not_current_soc():
    """Rollierende Optimierung: End-SOC = Anker (Simulationsstart), nicht aktueller SOC."""
    anchor_soc = 77.0
    current_soc = 55.0
    battery_params = _battery_params(end_soc_equals_start=True)
    matrix = _price_matrix(hours=12)
    model = _build_milp_model(matrix, 12, battery_params, current_soc, [])
    _add_milp_objective(model, matrix, 3.5)
    e_terminal = (anchor_soc / 100.0) * battery_params["battery_capacity_kwh"]
    _add_terminal_soc_constraint(model, e_terminal)

    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"

    end_energy = model.e_batt[-1].varValue
    e_current = (current_soc / 100.0) * battery_params["battery_capacity_kwh"]
    assert end_energy is not None
    assert abs(end_energy - e_terminal) < 1e-4
    assert abs(end_energy - e_current) > 0.05
