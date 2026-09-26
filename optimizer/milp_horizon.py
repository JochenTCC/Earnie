"""MILP-Horizontmodell: Variablen, Energiebilanz, SOC-Randbedingungen, Zielfunktion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pulp

from data.feed_in_prices import k_push_act_for_matrix_row
from .battery import effective_p_act
from .consumer_power import power_limits_kw
from .eauto_milp import milp_binary_charge_kw
from .milp_consumers import (
    _add_consumer_power_variables,
    _flex_power_at_t,
)
from .slot_duration import DEFAULT_DT_H, validate_dt_h

EMPTY_MILP_PLAN = {
    "p_grid_buy": 0.0,
    "p_grid_sell": 0.0,
    "p_charge": 0.0,
    "p_discharge": 0.0,
}


@dataclass
class MilpHorizonModel:
    prob: pulp.LpProblem
    horizon: int
    p_grid_buy: list
    p_grid_sell: list
    p_charge: list
    p_discharge: list
    e_batt: list
    consumer_on: dict[str, list]
    consumer_p: dict[str, list]
    consumer_p_fixed: dict[str, list]
    consumer_pv_follow: dict[str, list]
    planned_consumers: list
    consumer_milp_charge_kw: dict[str, float]
    dt_h: float


def _normalize_fixed_flex_by_t(
    fixed_flex_kw_t0_or_by_t: float | dict[int, float] | None,
) -> dict[int, float]:
    """Accept legacy t0 float or hour→kW map for preset flex outside MILP vars."""
    if fixed_flex_kw_t0_or_by_t is None:
        return {}
    if isinstance(fixed_flex_kw_t0_or_by_t, (int, float)):
        value = float(fixed_flex_kw_t0_or_by_t)
        return {0: value} if value > 1e-12 else {}
    return {
        int(slot): float(power)
        for slot, power in fixed_flex_kw_t0_or_by_t.items()
        if float(power) > 1e-12
    }


@dataclass
class _GridBatteryVars:
    """Netz- und Batterievariablen eines Solve-Fensters inkl. Big-M-Schranke."""

    p_grid_buy: list
    p_grid_sell: list
    p_charge: list
    p_discharge: list
    e_batt: list
    delta_charge: list
    delta_import: list
    big_m_grid: float


@dataclass
class _ConsumerVarBlock:
    """Verbrauchervariablen-Maps, wie sie MilpHorizonModel erwartet."""

    consumer_on: dict[str, list]
    consumer_p: dict[str, list]
    consumer_p_fixed: dict[str, list]
    consumer_pv_follow: dict[str, list]
    consumer_milp_charge_kw: dict[str, float]


def _create_grid_battery_vars(
    matrix: list[dict[str, Any]],
    horizon: int,
    battery_params: dict,
    planned_consumers: list,
) -> _GridBatteryVars:
    """LpVariables für Netzbezug/-einspeisung, Lade-/Entladeleistung und SOC-Energie."""
    min_soc = battery_params["min_soc"]
    max_soc = battery_params["max_soc"]
    max_power = battery_params["max_power_kw"]
    battery_capacity = battery_params["battery_capacity_kwh"]
    e_min = (min_soc / 100.0) * battery_capacity
    e_max = (max_soc / 100.0) * battery_capacity

    p_grid_buy = [pulp.LpVariable(f"p_grid_buy_{t}", lowBound=0) for t in range(horizon)]
    p_grid_sell = [pulp.LpVariable(f"p_grid_sell_{t}", lowBound=0) for t in range(horizon)]
    p_charge = [
        pulp.LpVariable(f"p_charge_{t}", lowBound=0, upBound=max_power)
        for t in range(horizon)
    ]
    p_discharge = [
        pulp.LpVariable(f"p_discharge_{t}", lowBound=0, upBound=max_power)
        for t in range(horizon)
    ]
    e_batt = [
        pulp.LpVariable(f"e_batt_{t}", lowBound=e_min, upBound=e_max)
        for t in range(horizon)
    ]
    delta_charge = [pulp.LpVariable(f"delta_charge_{t}", cat=pulp.LpBinary) for t in range(horizon)]
    max_flex_power = sum(power_limits_kw(c)[1] for c in planned_consumers)
    max_load = max(
        (effective_p_act(row, battery_params) for row in matrix[:horizon]),
        default=0.0,
    )
    max_pv = max((row["expected_p_pv"] for row in matrix[:horizon]), default=0.0)
    big_m_grid = max(max_load + max_flex_power + max_power, max_pv + max_power, 50.0)
    delta_import = [pulp.LpVariable(f"delta_import_{t}", cat=pulp.LpBinary) for t in range(horizon)]
    return _GridBatteryVars(
        p_grid_buy=p_grid_buy,
        p_grid_sell=p_grid_sell,
        p_charge=p_charge,
        p_discharge=p_discharge,
        e_batt=e_batt,
        delta_charge=delta_charge,
        delta_import=delta_import,
        big_m_grid=big_m_grid,
    )


def _add_consumer_var_block(
    prob: pulp.LpProblem,
    matrix: list[dict[str, Any]],
    horizon: int,
    planned_consumers: list,
    remaining_by_consumer: dict[str, float],
    ev_milp_params_by_id: dict[str, dict[str, float]],
    consumer_continue_on: dict[str, bool] | None,
) -> _ConsumerVarBlock:
    """On/Leistung/PV-Follow je geplantem Verbraucher plus Binär-Ladeleistung."""
    block = _ConsumerVarBlock(
        consumer_on={},
        consumer_p={},
        consumer_p_fixed={},
        consumer_pv_follow={},
        consumer_milp_charge_kw={},
    )
    continue_on = consumer_continue_on or {}
    for consumer in planned_consumers:
        cid = consumer["id"]
        rem = remaining_by_consumer.get(cid, 0.0)
        ev_params = ev_milp_params_by_id.get(cid)
        block.consumer_milp_charge_kw[cid] = milp_binary_charge_kw(
            consumer, matrix, rem, ev_params
        )
        _add_consumer_power_variables(
            prob,
            consumer,
            horizon,
            matrix,
            block.consumer_on,
            block.consumer_p,
            block.consumer_p_fixed,
            block.consumer_pv_follow,
            rem,
            ev_params,
            continue_on=bool(continue_on.get(cid, False)),
        )
    return block


def _add_slot_power_balance_and_soc(
    prob: pulp.LpProblem,
    matrix_row: dict[str, Any],
    battery_params: dict,
    grid_vars: _GridBatteryVars,
    consumer_vars: _ConsumerVarBlock,
    planned_consumers: list,
    fixed_flex: float,
    *,
    t: int,
    e_init: float,
    dt_h: float,
) -> None:
    """Energiebilanz, Exklusivität und SOC-Rekursion für einen Slot."""
    max_power = battery_params["max_power_kw"]
    efficiency = battery_params["efficiency"]
    p_grid_buy = grid_vars.p_grid_buy
    p_grid_sell = grid_vars.p_grid_sell
    p_charge = grid_vars.p_charge
    p_discharge = grid_vars.p_discharge
    e_batt = grid_vars.e_batt
    delta_charge = grid_vars.delta_charge
    delta_import = grid_vars.delta_import
    big_m_grid = grid_vars.big_m_grid
    p_pv = matrix_row["expected_p_pv"]
    p_con = effective_p_act(matrix_row, battery_params)
    p_flex = fixed_flex + pulp.lpSum(
        _flex_power_at_t(
            consumer,
            consumer_vars.consumer_on,
            consumer_vars.consumer_p,
            consumer_vars.consumer_milp_charge_kw[consumer["id"]],
            t,
        )
        for consumer in planned_consumers
    )
    prob += (
        p_pv + p_grid_buy[t] + p_discharge[t]
        == p_con + p_flex + p_grid_sell[t] + p_charge[t]
    )
    prob += p_grid_buy[t] <= big_m_grid * delta_import[t]
    prob += p_grid_sell[t] <= big_m_grid * (1 - delta_import[t])
    prob += p_charge[t] <= max_power * delta_charge[t]
    prob += p_discharge[t] <= max_power * (1 - delta_charge[t])
    _add_control_slot_constraints(
        prob,
        battery_params,
        t=t,
        p_pv=p_pv,
        p_con=p_con,
        p_flex=p_flex,
        p_grid_buy=p_grid_buy[t],
        p_grid_sell=p_grid_sell[t],
        p_charge=p_charge[t],
        p_discharge=p_discharge[t],
        delta_import=delta_import[t],
        max_power=max_power,
        big_m_grid=big_m_grid,
    )
    prev_e = e_init if t == 0 else e_batt[t - 1]
    prob += (
        e_batt[t]
        == prev_e + (p_charge[t] * efficiency - p_discharge[t] / efficiency) * dt_h
    )


def _add_power_balance_and_soc_dynamics(
    prob: pulp.LpProblem,
    matrix: list[dict[str, Any]],
    battery_params: dict,
    current_soc: float,
    grid_vars: _GridBatteryVars,
    consumer_vars: _ConsumerVarBlock,
    planned_consumers: list,
    fixed_flex_by_t: dict[int, float],
    *,
    horizon: int,
    dt_h: float,
) -> None:
    """Energiebilanz, Netz-/Batterie-Exklusivität und SOC-Rekursion je Slot."""
    e_init = (current_soc / 100.0) * battery_params["battery_capacity_kwh"]
    for t in range(horizon):
        _add_slot_power_balance_and_soc(
            prob,
            matrix[t],
            battery_params,
            grid_vars,
            consumer_vars,
            planned_consumers,
            float(fixed_flex_by_t.get(t, 0.0)),
            t=t,
            e_init=e_init,
            dt_h=dt_h,
        )


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
    if control == BATTERY_CONTROL_READ_ONLY:
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
) -> None:
    """Pin battery+grid to residual split (greedy self-consumption accounting)."""
    surplus = pulp.LpVariable(f"sc_surplus_{t}", lowBound=0)
    deficit = pulp.LpVariable(f"sc_deficit_{t}", lowBound=0)
    delta_surplus = pulp.LpVariable(f"sc_delta_surplus_{t}", cat="Binary")
    residual = p_pv - p_con - p_flex
    prob += surplus - deficit == residual
    prob += surplus <= big_m * delta_surplus
    prob += deficit <= big_m * (1 - delta_surplus)
    prob += p_charge + p_grid_sell == surplus
    prob += p_discharge + p_grid_buy == deficit


def _build_milp_model(
    matrix: list[dict[str, Any]],
    horizon: int,
    battery_params: dict,
    current_soc: float,
    planned_consumers: list,
    fixed_flex_kw_t0_or_by_t: float | dict[int, float],
    remaining_by_consumer: dict[str, float],
    ev_milp_params_by_id: dict[str, dict[str, float]],
    consumer_continue_on: dict[str, bool] | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> MilpHorizonModel:
    dt_h = validate_dt_h(dt_h)
    prob = pulp.LpProblem("Energy_Cost_Minimization", pulp.LpMinimize)
    grid_vars = _create_grid_battery_vars(
        matrix, horizon, battery_params, planned_consumers
    )
    consumer_vars = _add_consumer_var_block(
        prob,
        matrix,
        horizon,
        planned_consumers,
        remaining_by_consumer,
        ev_milp_params_by_id,
        consumer_continue_on,
    )
    _add_power_balance_and_soc_dynamics(
        prob,
        matrix,
        battery_params,
        current_soc,
        grid_vars,
        consumer_vars,
        planned_consumers,
        _normalize_fixed_flex_by_t(fixed_flex_kw_t0_or_by_t),
        horizon=horizon,
        dt_h=dt_h,
    )
    return MilpHorizonModel(
        prob=prob,
        horizon=horizon,
        p_grid_buy=grid_vars.p_grid_buy,
        p_grid_sell=grid_vars.p_grid_sell,
        p_charge=grid_vars.p_charge,
        p_discharge=grid_vars.p_discharge,
        e_batt=grid_vars.e_batt,
        consumer_on=consumer_vars.consumer_on,
        consumer_p=consumer_vars.consumer_p,
        consumer_p_fixed=consumer_vars.consumer_p_fixed,
        consumer_pv_follow=consumer_vars.consumer_pv_follow,
        planned_consumers=planned_consumers,
        consumer_milp_charge_kw=consumer_vars.consumer_milp_charge_kw,
        dt_h=dt_h,
    )


def _add_terminal_soc_constraint(model: MilpHorizonModel, e_terminal: float) -> None:
    """End-SOC am Horizontende = Ziel-SOC (Anker zu Simulations-/Planungsbeginn)."""
    if model.horizon < 1:
        return
    model.prob += model.e_batt[model.horizon - 1] == e_terminal


def _add_soc_equality_constraint(
    model: MilpHorizonModel,
    slot_index: int,
    e_kwh: float,
) -> None:
    """SOC at slot_index equals e_kwh (sunrise floor or SE SA₁ carry-in)."""
    if model.horizon < 1:
        return
    if slot_index < 0 or slot_index >= model.horizon:
        raise ValueError(
            f"soc equality index {slot_index} liegt außerhalb des Horizonts "
            f"(0..{model.horizon - 1})."
        )
    model.prob += model.e_batt[slot_index] == e_kwh


def _add_sunrise_soc_min_constraint(
    model: MilpHorizonModel,
    sunrise_index: int,
    e_min_kwh: float,
) -> None:
    """
    Legacy no-op: ``e_batt`` already has lowBound=e_min every slot.

    Hard ``e_batt[sunrise] == SOC_min`` forced dumping residual evening SoC at SA₁
    (Chart jump ~20%→10%). Live uses PV-only charge through sunrise instead; SE
    SA₁ carry-in uses ``_add_soc_equality_constraint``.
    """
    del model, sunrise_index, e_min_kwh


def _add_pv_only_charge_through_sunrise(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    sunrise_index: int,
) -> None:
    """
    No grid-charged battery increase through the sunrise SOC_min slot.

    Hourly MPC otherwise charges before SA₁ for later flex, then re-opts the flex
    away and is forced to export to meet SOC_min (SoC spike at SA₁). Spec assumes
    night grid charge is economically irrelevant for this battery size.
    """
    if model.horizon < 1:
        return
    last = min(sunrise_index, model.horizon - 1)
    if last < 0:
        return
    for t in range(last + 1):
        pv_cap = max(0.0, float(matrix[t].get("expected_p_pv", 0.0) or 0.0))
        model.prob += model.p_charge[t] <= pv_cap


def _terminal_soc_energy_kwh(
    battery_params: dict,
    terminal_soc_percent: float | None,
) -> float | None:
    if terminal_soc_percent is None:
        return None
    return (terminal_soc_percent / 100.0) * battery_params["battery_capacity_kwh"]


def _add_milp_objective(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    fallback_k_push: float,
    ev_milp_params_by_id: dict[str, dict[str, float]],
    *,
    wear_cent_per_kwh: float,
) -> None:
    dt_h = validate_dt_h(model.dt_h)
    energy_cost = pulp.lpSum([
        (
            model.p_grid_buy[t] * matrix[t]["k_act"]
            - model.p_grid_sell[t]
            * k_push_act_for_matrix_row(matrix[t], fallback_k_push)
        )
        * dt_h
        for t in range(model.horizon)
    ])
    wear_cost = 0.0
    if wear_cent_per_kwh > 0.0:
        wear_cost = wear_cent_per_kwh * dt_h * pulp.lpSum(
            model.p_charge[t] + model.p_discharge[t]
            for t in range(model.horizon)
        )
    tie_break = 0.0
    for cid, ev_params in (ev_milp_params_by_id or {}).items():
        if cid not in model.consumer_on:
            continue
        on_vars = model.consumer_on[cid]
        eps_on = ev_params["tie_break_on_epsilon"]
        eps_time = ev_params["tie_break_time_epsilon"]
        tie_break += eps_on * pulp.lpSum(on_vars) + eps_time * pulp.lpSum(
            t * on_vars[t] for t in range(len(on_vars))
        )
    model.prob += energy_cost + wear_cost + tie_break
