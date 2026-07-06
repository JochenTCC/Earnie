"""Entladesperre: Ziel-SOC und Huawei-Mapping."""
from __future__ import annotations

from unittest.mock import MagicMock

from optimizer import battery as bat
from optimizer.milp import _derive_control_from_milp

_BATTERY_PARAMS = {
    "min_soc": 10.0,
    "max_soc": 100.0,
    "max_power_kw": 5.0,
    "battery_capacity_kwh": 10.0,
    "efficiency": 0.95,
}


def _model_with_soc_percent(percent: float) -> MagicMock:
    model = MagicMock()
    capacity = _BATTERY_PARAMS["battery_capacity_kwh"]
    model.e_batt = [MagicMock(varValue=capacity * percent / 100.0)]
    return model


def test_entladesperre_target_soc_matches_current_soc():
    current_soc = 41.0
    mode, target_power, target_soc = _derive_control_from_milp(
        _model_with_soc_percent(50.0),
        [{"expected_p_pv": 0.0, "expected_p_act": 2.0}],
        {"p_charge": 0.0, "p_discharge": 0.0, "p_grid_buy": 0.5},
        {},
        0.0,
        current_soc,
        _BATTERY_PARAMS,
    )
    assert mode == bat.MODE_ENTLADESPERRE
    assert target_power == 0.0
    assert target_soc == current_soc
