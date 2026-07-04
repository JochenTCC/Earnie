"""Tests für Batterieverschleiß in der MILP-Zielfunktion."""
from __future__ import annotations

import pulp
import pytest

from optimizer.battery_wear import (
    battery_wear_cent_per_kwh_from_config,
    throughput_wear_cent_per_kwh,
    validate_battery_wear_config,
)
from optimizer.milp import _add_milp_objective, _build_milp_model


def test_throughput_wear_backlog_defaults():
    cent = throughput_wear_cent_per_kwh(
        replacement_cost_euro=1500.0,
        expected_cycles=6000.0,
        cycle_cost_fraction=0.5,
        capacity_kwh=5.0,
    )
    assert cent == pytest.approx(2.5)


def test_validate_requires_enabled_flag():
    with pytest.raises(ValueError, match="battery_wear.enabled"):
        validate_battery_wear_config({"replacement_cost_euro": 1500})


def test_disabled_wear_returns_zero():
    wear = validate_battery_wear_config({"enabled": False})
    assert battery_wear_cent_per_kwh_from_config(wear, 5.0) == 0.0


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.95,
    }


def _shift_matrix() -> list[dict]:
    """Gleicher Strompreis; PV/Last erlauben optionalen Batterie-Durchsatz."""
    rows = []
    for hour, pv, load in ((0, 4.0, 0.0), (1, 0.0, 4.0)):
        rows.append(
            {
                "hour": hour,
                "expected_p_pv": pv,
                "expected_p_act": load,
                "k_act": 20.0,
                "k_push_act": 3.5,
                "expected_flex_kw": {},
            }
        )
    return rows


def _total_battery_throughput(model) -> float:
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
    charge = sum(float(v.varValue or 0.0) for v in model.p_charge)
    discharge = sum(float(v.varValue or 0.0) for v in model.p_discharge)
    return charge + discharge


def test_wear_reduces_battery_throughput_at_equal_prices():
    matrix = _shift_matrix()
    params = _battery_params()
    model_no_wear = _build_milp_model(matrix, 2, params, 50.0, [], 0.0, {}, None)
    _add_milp_objective(
        model_no_wear, matrix, 3.5, None, wear_cent_per_kwh=0.0
    )
    throughput_no_wear = _total_battery_throughput(model_no_wear)

    model_wear = _build_milp_model(matrix, 2, params, 50.0, [], 0.0, {}, None)
    _add_milp_objective(
        model_wear, matrix, 3.5, None, wear_cent_per_kwh=10.0
    )
    throughput_wear = _total_battery_throughput(model_wear)

    assert throughput_wear <= throughput_no_wear + 1e-6
    assert throughput_wear < throughput_no_wear - 0.1


def test_wear_allows_profitable_arbitrage():
    matrix = [
        {
            "hour": 0,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.0,
            "k_act": 5.0,
            "k_push_act": 3.5,
            "expected_flex_kw": {},
        },
        {
            "hour": 1,
            "expected_p_pv": 0.0,
            "expected_p_act": 4.0,
            "k_act": 40.0,
            "k_push_act": 3.5,
            "expected_flex_kw": {},
        },
    ]
    params = _battery_params()
    model = _build_milp_model(matrix, 2, params, 50.0, [], 0.0, {}, None)
    _add_milp_objective(model, matrix, 3.5, None, wear_cent_per_kwh=2.5)
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
    assert float(model.p_charge[0].varValue or 0.0) > 0.5
    assert float(model.p_discharge[1].varValue or 0.0) > 0.5
