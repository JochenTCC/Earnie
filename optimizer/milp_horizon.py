"""MILP-Horizontmodell: Variablen, Energiebilanz, SOC-Randbedingungen, Zielfunktion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pulp

from data.feed_in_prices import k_push_act_for_matrix_row
from .consumer_power import power_limits_kw
from .eauto_milp import milp_binary_charge_kw
from .milp_consumers import (
    _add_consumer_power_variables,
    _flex_power_at_t,
)

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


def _build_milp_model(
    matrix: list[dict[str, Any]],
    horizon: int,
    battery_params: dict,
    current_soc: float,
    planned_consumers: list,
    fixed_flex_kw_t0: float,
    remaining_by_consumer: dict[str, float],
    ev_milp_params_by_id: dict[str, dict[str, float]],
    consumer_continue_on: dict[str, bool] | None = None,
) -> MilpHorizonModel:
    min_soc = battery_params["min_soc"]
    max_soc = battery_params["max_soc"]
    max_power = battery_params["max_power_kw"]
    battery_capacity = battery_params["battery_capacity_kwh"]
    efficiency = battery_params["efficiency"]
    e_min = (min_soc / 100.0) * battery_capacity
    e_max = (max_soc / 100.0) * battery_capacity
    e_init = (current_soc / 100.0) * battery_capacity

    prob = pulp.LpProblem("Energy_Cost_Minimization", pulp.LpMinimize)
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
    max_load = max((row["expected_p_act"] for row in matrix[:horizon]), default=0.0)
    max_pv = max((row["expected_p_pv"] for row in matrix[:horizon]), default=0.0)
    big_m_grid = max(max_load + max_flex_power + max_power, max_pv + max_power, 50.0)
    delta_import = [pulp.LpVariable(f"delta_import_{t}", cat=pulp.LpBinary) for t in range(horizon)]

    consumer_on: dict[str, list] = {}
    consumer_p: dict[str, list] = {}
    consumer_p_fixed: dict[str, list] = {}
    consumer_pv_follow: dict[str, list] = {}
    consumer_milp_charge_kw: dict[str, float] = {}
    continue_on = consumer_continue_on or {}
    for consumer in planned_consumers:
        cid = consumer["id"]
        rem = remaining_by_consumer.get(cid, 0.0)
        ev_params = ev_milp_params_by_id.get(cid)
        consumer_milp_charge_kw[cid] = milp_binary_charge_kw(
            consumer, matrix, rem, ev_params
        )
        _add_consumer_power_variables(
            prob,
            consumer,
            horizon,
            matrix,
            consumer_on,
            consumer_p,
            consumer_p_fixed,
            consumer_pv_follow,
            rem,
            ev_params,
            continue_on=bool(continue_on.get(cid, False)),
        )

    for t in range(horizon):
        p_pv = matrix[t]["expected_p_pv"]
        p_con = matrix[t]["expected_p_act"]
        fixed_flex = fixed_flex_kw_t0 if t == 0 else 0.0
        p_flex = fixed_flex + pulp.lpSum(
            _flex_power_at_t(
                consumer,
                consumer_on,
                consumer_p,
                consumer_milp_charge_kw[consumer["id"]],
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
        if t == 0:
            prob += (
                e_batt[t]
                == e_init + p_charge[t] * efficiency - p_discharge[t] / efficiency
            )
        else:
            prob += (
                e_batt[t]
                == e_batt[t - 1] + p_charge[t] * efficiency - p_discharge[t] / efficiency
            )

    return MilpHorizonModel(
        prob=prob,
        horizon=horizon,
        p_grid_buy=p_grid_buy,
        p_grid_sell=p_grid_sell,
        p_charge=p_charge,
        p_discharge=p_discharge,
        e_batt=e_batt,
        consumer_on=consumer_on,
        consumer_p=consumer_p,
        consumer_p_fixed=consumer_p_fixed,
        consumer_pv_follow=consumer_pv_follow,
        planned_consumers=planned_consumers,
        consumer_milp_charge_kw=consumer_milp_charge_kw,
    )


def _add_terminal_soc_constraint(model: MilpHorizonModel, e_terminal: float) -> None:
    """End-SOC am Horizontende = Ziel-SOC (Anker zu Simulations-/Planungsbeginn)."""
    if model.horizon < 1:
        return
    model.prob += model.e_batt[model.horizon - 1] == e_terminal


def _add_sunrise_soc_min_constraint(
    model: MilpHorizonModel,
    sunrise_index: int,
    e_min_kwh: float,
) -> None:
    """SOC am Sonnenaufgang-Slot = SOC_min (Live Sunset-Horizont)."""
    if model.horizon < 1:
        return
    if sunrise_index < 0 or sunrise_index >= model.horizon:
        raise ValueError(
            f"sunrise_soc_min_index {sunrise_index} liegt außerhalb des Horizonts "
            f"(0..{model.horizon - 1})."
        )
    model.prob += model.e_batt[sunrise_index] == e_min_kwh


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
    energy_cost = pulp.lpSum([
        model.p_grid_buy[t] * matrix[t]["k_act"]
        - model.p_grid_sell[t]
        * k_push_act_for_matrix_row(matrix[t], fallback_k_push)
        for t in range(model.horizon)
    ])
    wear_cost = 0.0
    if wear_cent_per_kwh > 0.0:
        wear_cost = wear_cent_per_kwh * pulp.lpSum(
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
