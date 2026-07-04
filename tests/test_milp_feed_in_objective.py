"""MILP-Zielfunktion nutzt stündliches k_push_act aus der Matrix."""
from __future__ import annotations

import pulp

from optimizer.milp import _add_milp_objective, _build_milp_model


def _matrix_with_feed_in(*, sell_high_hour: int) -> list[dict]:
    rows = []
    for h in range(4):
        rows.append(
            {
                "hour": h,
                "expected_p_pv": 5.0,
                "expected_p_act": 0.0,
                "k_act": 30.0,
                "k_push_act": 20.0 if h == sell_high_hour else 2.0,
                "expected_flex_kw": {},
            }
        )
    return rows


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.95,
    }


def _grid_sell_kwh(model, matrix) -> list[float]:
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False, gapRel=0.1))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
    return [float(model.p_grid_sell[t].varValue or 0.0) for t in range(len(matrix))]


def test_milp_prefers_export_in_high_feed_in_hour():
    matrix = _matrix_with_feed_in(sell_high_hour=2)
    model = _build_milp_model(matrix, 4, _battery_params(), 50.0, [], 0.0, {}, None)
    _add_milp_objective(
        model, matrix, fallback_k_push=2.0, eauto_milp_params=None, wear_cent_per_kwh=0.0
    )
    sells = _grid_sell_kwh(model, matrix)
    assert sells[2] > sells[0] + 0.1
