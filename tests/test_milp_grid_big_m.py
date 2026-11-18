"""Grid Big-M must cover fixed (preset) flex power such as preset EV charging."""
from __future__ import annotations

import pulp

from optimizer.milp import _add_milp_objective, _build_milp_model


def _matrix(slots: int) -> list[dict]:
    return [
        {
            "hour": t,
            "expected_p_pv": 0.0,
            "expected_p_act": 1.0,
            "k_act": 30.0,
            "k_push_act": 5.0,
            "expected_flex_kw": {},
        }
        for t in range(slots)
    ]


def _small_battery() -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.95,
    }


def test_big_m_grid_covers_fixed_flex_power():
    # Preset EV charging (fixed flex, not a planned consumer) of 60 kW on top of 1 kW base
    # load exceeds load + battery headroom and the 50 kW floor of the Big-M bound.
    matrix = _matrix(2)
    fixed_flex_by_t = {0: 60.0, 1: 0.0}
    model = _build_milp_model(matrix, 2, _small_battery(), 10.0, [], fixed_flex_by_t, {}, {})
    _add_milp_objective(
        model, matrix, fallback_k_push=5.0, ev_milp_params_by_id={}, wear_cent_per_kwh=0.0
    )
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
    assert float(model.p_grid_buy[0].varValue or 0.0) >= 60.0 + 1.0 - 2.5 - 1e-6
