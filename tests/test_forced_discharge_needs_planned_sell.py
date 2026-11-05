"""A SoC above plan is no reason to export: forced discharge needs a planned grid sale."""
from __future__ import annotations

from optimizer import battery as bat

_BATTERY = {
    "id": "akku",
    "min_soc": 10.0,
    "max_soc": 100.0,
    "max_power_kw": 15.5,
    "battery_capacity_kwh": 31.0,
    "efficiency": 0.95,
    "control": "full",
    "threshold_power": 0.05,
}
_ROW = {"expected_p_pv": 7.5, "expected_p_act": 0.5}


def _mode(sell_kw: float) -> int:
    plan = {"p_charge": 0.0, "p_discharge": 2.2, "p_grid_buy": 0.0, "p_grid_sell": sell_kw}
    mode, _, _ = bat.derive_control_from_milp_plan(
        plan, _ROW, total_flex_power=7.05, current_soc=21.0, planned_soc=10.3, battery_params=_BATTERY, dt_h=0.25
    )
    return mode


def test_soc_above_plan_does_not_force_export() -> None:
    assert _mode(sell_kw=0.0) == bat.MODE_AUTOMATIK


def test_planned_sale_still_forces_discharge() -> None:
    assert _mode(sell_kw=5.0) == bat.MODE_ZWANGS_ENTLADEN
