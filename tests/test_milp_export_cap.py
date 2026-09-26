"""MILP hard export power cap (2.7.a)."""
from __future__ import annotations

import pulp

from optimizer.milp import _add_milp_objective, _build_milp_model, milp_optimizer


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.95,
        "control": "full",
    }


def _surplus_matrix(*, k_push: float = 20.0, hours: int = 2, p_pv: float = 3.0) -> list[dict]:
    return [
        {
            "hour": h,
            "expected_p_pv": p_pv,
            "expected_p_act": 0.5,
            "k_act": 30.0,
            "k_push_act": k_push,
            "expected_flex_kw": {},
        }
        for h in range(hours)
    ]


def test_milp_respects_hard_export_cap() -> None:
    # PV 3 kW − load 0.5 → 2.5 surplus; battery can take 2.5, sell cap 1.0 is feasible.
    matrix = _surplus_matrix(p_pv=3.0)
    model = _build_milp_model(
        matrix,
        2,
        _battery_params(),
        50.0,
        [],
        0.0,
        {},
        {},
        export_caps_kw=[1.0, 1.0],
    )
    _add_milp_objective(
        model, matrix, fallback_k_push=20.0, ev_milp_params_by_id={}, wear_cent_per_kwh=0.0
    )
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False, gapRel=0.1))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
    for t in range(2):
        sell = float(model.p_grid_sell[t].varValue or 0.0)
        assert sell <= 1.0 + 1e-6


def test_milp_pay_to_export_hard_zero_via_optimizer() -> None:
    matrix = _surplus_matrix(k_push=-5.0)
    _, _, _, _, _, plan, _ = milp_optimizer(
        matrix,
        current_hour=0,
        current_soc=50.0,
        battery_params=_battery_params(),
        k_push=-5.0,
        verbose=False,
        consumers=[],
    )
    assert float(plan.get("p_grid_sell", 0.0)) <= 1e-6


def test_milp_unconstrained_still_solves() -> None:
    matrix = _surplus_matrix(k_push=15.0)
    _, _, _, _, _, plan, _ = milp_optimizer(
        matrix,
        current_hour=0,
        current_soc=50.0,
        battery_params=_battery_params(),
        k_push=15.0,
        verbose=False,
        consumers=[],
    )
    assert float(plan.get("p_grid_sell", 0.0)) >= 0.0
