"""Battery control envelope per MILP slot (limits_only / read_only, self-consumption coupling).

Split out of ``optimizer.milp_horizon`` (still re-exported there).
"""
from __future__ import annotations

import pulp


def _add_control_slot_constraints(
    prob: pulp.LpProblem,
    battery_params: dict,
    *,
    t: int,
    p_pv: float,
    p_con: float,
    p_flex,
    p_grid_buy,
    p_grid_sell,
    p_charge,
    p_discharge,
    delta_import,
    max_power: float,
    big_m_grid: float,
    suffix: str = "",
    apply_self_consumption: bool = True,
) -> None:
    """Apply limits_only / read_only envelope (full = no extra constraints)."""
    from house_config.battery_control import (
        BATTERY_CONTROL_LIMITS_ONLY,
        BATTERY_CONTROL_READ_ONLY,
        control_from_battery_params,
    )

    control = control_from_battery_params(battery_params)
    if control not in (BATTERY_CONTROL_LIMITS_ONLY, BATTERY_CONTROL_READ_ONLY):
        return
    # No grid charge / no battery export
    prob += p_charge <= max_power * (1 - delta_import)
    prob += p_discharge <= max_power * delta_import
    # Charge from PV only; discharge covers house load only
    prob += p_charge <= float(p_pv)
    prob += p_discharge <= p_con + p_flex
    if control == BATTERY_CONTROL_READ_ONLY and apply_self_consumption:
        _add_self_consumption_coupling(
            prob,
            t=t,
            p_pv=float(p_pv),
            p_con=float(p_con),
            p_flex=p_flex,
            p_grid_buy=p_grid_buy,
            p_grid_sell=p_grid_sell,
            p_charge=p_charge,
            p_discharge=p_discharge,
            big_m=max(big_m_grid, max_power, 1.0),
            suffix=suffix,
        )


def _add_self_consumption_coupling(
    prob: pulp.LpProblem,
    *,
    t: int,
    p_pv: float,
    p_con: float,
    p_flex,
    p_grid_buy,
    p_grid_sell,
    p_charge,
    p_discharge,
    big_m: float,
    suffix: str = "",
) -> None:
    """Pin battery+grid to residual split (greedy self-consumption accounting)."""
    tag = f"_{suffix}" if suffix else ""
    surplus = pulp.LpVariable(f"sc_surplus{tag}_{t}", lowBound=0)
    deficit = pulp.LpVariable(f"sc_deficit{tag}_{t}", lowBound=0)
    delta_surplus = pulp.LpVariable(f"sc_delta_surplus{tag}_{t}", cat="Binary")
    residual = p_pv - p_con - p_flex
    prob += surplus - deficit == residual
    prob += surplus <= big_m * delta_surplus
    prob += deficit <= big_m * (1 - delta_surplus)
    prob += p_charge + p_grid_sell == surplus
    prob += p_discharge + p_grid_buy == deficit
