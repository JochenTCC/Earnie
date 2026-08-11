"""Batterie-Standby als 24/7-AC-Last in MILP und Hilfsfunktionen."""
from __future__ import annotations

import pulp
import pytest

from optimizer.battery import effective_p_act, standby_power_kw
from optimizer.milp import _add_milp_objective, _build_milp_model


def _battery_params(*, standby: float = 0.0) -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.95,
        "standby_power_kw": standby,
    }


def test_standby_power_kw_helper():
    assert standby_power_kw({}) == 0.0
    assert standby_power_kw({"standby_power_kw": 0.05}) == pytest.approx(0.05)
    assert standby_power_kw({"standby_power_kw": -1.0}) == 0.0


def test_scenario_to_battery_params_preserves_standby():
    from simulation.engine import _scenario_to_battery_params

    params = _scenario_to_battery_params(
        {
            "battery_capacity_kwh": 15.0,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "battery_max_power_kw": 5.0,
            "battery_efficiency": 0.94,
            "standby_power_kw": 1.0,
        }
    )
    assert params["standby_power_kw"] == pytest.approx(1.0)


def test_effective_p_act_adds_standby():
    row = {"expected_p_act": 1.2}
    assert effective_p_act(row, _battery_params(standby=0.08)) == pytest.approx(1.28)


def test_milp_idle_imports_baseload_plus_standby():
    """Ohne PV: Netzbezug ≈ Grundlast + Standby; SoC bleibt (kein Entladen nötig)."""
    matrix = [
        {
            "hour": 0,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.5,
            "k_act": 20.0,
            "k_push_act": 0.0,
            "expected_flex_kw": {},
        }
    ]
    params = _battery_params(standby=0.1)
    model = _build_milp_model(matrix, 1, params, params["min_soc"], [], 0.0, {}, None)
    _add_milp_objective(model, matrix, 0.0, None, wear_cent_per_kwh=0.0)
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
    buy = float(model.p_grid_buy[0].varValue or 0.0)
    charge = float(model.p_charge[0].varValue or 0.0)
    discharge = float(model.p_discharge[0].varValue or 0.0)
    assert buy == pytest.approx(0.6, abs=1e-3)
    assert charge == pytest.approx(0.0, abs=1e-3)
    assert discharge == pytest.approx(0.0, abs=1e-3)
    e_end = float(model.e_batt[0].varValue or 0.0)
    e_min = (params["min_soc"] / 100.0) * params["battery_capacity_kwh"]
    assert e_end == pytest.approx(e_min, abs=1e-3)
