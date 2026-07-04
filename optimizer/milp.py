"""MILP-Optimierung für Batterie und flexible Verbraucher."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pulp

import config
from data.feed_in_prices import k_push_act_for_matrix_row
from .charging_context import (
    apply_charging_window_constraints,
    charging_schedule_enabled,
    consumer_charging_eligible_indices,
    latest_start_datetime,
    schedule_indices_for_consumer,
    split_eligible_by_urgent_deadline,
    summarize_urgent_rule_usage,
    urgent_charging_indices,
)
from .consumer_power import (
    estimate_pv_surplus_kw,
    power_limits_kw,
    uses_pv_follow,
)
from .eauto_milp import (
    milp_binary_charge_kw,
    milp_uses_power_setpoint,
    split_eauto_preset,
)
from . import battery as bat
from .cbc_solver import solve_with_strict_fallback
from .cbc_events import record_cbc_event, update_cbc_milp_context_from_row

logger = logging.getLogger(__name__)

EMPTY_MILP_PLAN = {
    "p_grid_buy": 0.0,
    "p_grid_sell": 0.0,
    "p_charge": 0.0,
    "p_discharge": 0.0,
}

_AUTOMATIK_FALLBACK = (0, 0.0, 99.0, {}, {}, EMPTY_MILP_PLAN, {})


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


def _day_indices(matrix: list[dict[str, Any]], horizon: int) -> list[int]:
    """Stunden im Planungshorizont, die zum selben Kalendertag wie t=0 gehören."""
    ref_date = matrix[0].get("date")
    if ref_date is None:
        return list(range(horizon))
    return [t for t in range(horizon) if matrix[t].get("date") == ref_date]


def _active_consumers(consumers: list | None) -> list:
    if consumers is not None:
        return consumers
    return config.get_flexible_consumers(optimizer_only=True)


def _remaining_kwh_by_consumer(
    active: list,
    consumer_remaining_kwh: dict[str, float] | None,
    spa_remaining_kwh: float | None,
) -> dict[str, float]:
    remaining: dict[str, float] = {}
    for consumer in active:
        cid = consumer["id"]
        if consumer_remaining_kwh and cid in consumer_remaining_kwh:
            remaining[cid] = max(0.0, float(consumer_remaining_kwh[cid]))
        else:
            remaining[cid] = float(consumer["daily_target_kwh"])
    if spa_remaining_kwh is not None and "swimspa" in remaining:
        remaining["swimspa"] = max(0.0, float(spa_remaining_kwh))
    return remaining


def add_min_on_time_constraints(
    prob: pulp.LpProblem,
    on_vars: list,
    min_on_quarterhours: int,
    prefix: str,
) -> None:
    """Erzwingt Mindest-Einschaltdauer; MILP arbeitet stündlich (4 Viertelstunden = 1 Slot)."""
    min_hours = max(1, (int(min_on_quarterhours) + 3) // 4)
    if min_hours <= 1:
        return
    horizon = len(on_vars)
    for t in range(horizon - min_hours + 1):
        prev = 0 if t == 0 else on_vars[t - 1]
        prob += pulp.lpSum(on_vars[t:t + min_hours]) >= min_hours * (on_vars[t] - prev)


def _max_deliverable_kwh(consumer: dict, eligible_indices: list[int]) -> float:
    _, max_kw = power_limits_kw(consumer)
    return len(eligible_indices) * max_kw


def _delivery_energy_expr(
    model: MilpHorizonModel,
    consumer: dict,
    eligible_indices: list[int],
):
    cid = consumer["id"]
    if cid in model.consumer_p:
        return pulp.lpSum(model.consumer_p[cid][t] for t in eligible_indices)
    charge_kw = model.consumer_milp_charge_kw[cid]
    return pulp.lpSum(
        charge_kw * model.consumer_on[cid][t]
        for t in eligible_indices
    )


def filter_feasible_consumers(
    consumers: list,
    remaining_kwh: dict[str, float],
    matrix: list,
    schedule_indices: list[int],
    verbose: bool,
    charging_contexts: dict[str, dict] | None,
) -> list:
    """Entfernt Verbraucher, deren Ziel im verbleibenden Horizont nicht erreichbar ist."""
    feasible = []
    contexts = charging_contexts or {}
    horizon = len(matrix)
    for consumer in consumers:
        cid = consumer["id"]
        target = remaining_kwh.get(cid, 0.0)
        if target <= 0:
            continue
        ctx = contexts.get(cid)
        if ctx is not None and not ctx.get("active", True):
            continue
        consumer_indices = schedule_indices_for_consumer(
            matrix, horizon, schedule_indices, consumer, ctx
        )
        eligible = consumer_charging_eligible_indices(
            matrix, consumer, consumer_indices, ctx
        )
        capacity_indices = eligible if eligible else consumer_indices
        max_deliverable = _max_deliverable_kwh(consumer, capacity_indices)
        if target > max_deliverable + 1e-6:
            if verbose:
                sched_hint = ""
                if charging_schedule_enabled(consumer):
                    sched_hint = f" ({len(eligible)} h im Ladezeitfenster)"
                logger.warning(
                    "%s: Ziel (%.2f kWh) nicht vollständig erreichbar "
                    "mit %s h à %.2f kW%s – lade mit Best-Effort.",
                    consumer["name"],
                    target,
                    len(capacity_indices),
                    power_limits_kw(consumer)[1],
                    sched_hint,
                )
        feasible.append(consumer)
    return feasible


def _flex_power_at_t(
    consumer: dict,
    consumer_on: dict[str, list],
    consumer_p: dict[str, list],
    charge_kw: float,
    t: int,
):
    cid = consumer["id"]
    if cid in consumer_p:
        return consumer_p[cid][t]
    return charge_kw * consumer_on[cid][t]


def _add_setpoint_power_variables(
    prob: pulp.LpProblem,
    consumer: dict,
    horizon: int,
    matrix: list[dict[str, Any]],
    consumer_on: dict[str, list],
    consumer_p: dict[str, list],
    consumer_p_fixed: dict[str, list],
    consumer_pv_follow: dict[str, list],
) -> None:
    """kW-Sollwert-Verbraucher: optional pv_follow (Überschuss) vs. feste Leistung."""
    cid = consumer["id"]
    min_kw, max_kw = power_limits_kw(consumer)
    big_m = max_kw + 1.0
    consumer_p[cid] = [
        pulp.LpVariable(f"{cid}_p_{t}", lowBound=0, upBound=max_kw)
        for t in range(horizon)
    ]
    if not uses_pv_follow(consumer):
        for t in range(horizon):
            prob += consumer_p[cid][t] <= max_kw * consumer_on[cid][t]
            if min_kw > 1e-9:
                prob += consumer_p[cid][t] >= min_kw * consumer_on[cid][t]
        return

    consumer_p_fixed[cid] = [
        pulp.LpVariable(f"{cid}_p_fix_{t}", lowBound=0, upBound=max_kw)
        for t in range(horizon)
    ]
    consumer_pv_follow[cid] = [
        pulp.LpVariable(f"{cid}_pv_{t}", cat=pulp.LpBinary)
        for t in range(horizon)
    ]
    for t in range(horizon):
        pv_est = estimate_pv_surplus_kw(matrix[t], max_kw)
        on_t = consumer_on[cid][t]
        pf_t = consumer_pv_follow[cid][t]
        p_t = consumer_p[cid][t]
        p_fix = consumer_p_fixed[cid][t]
        prob += pf_t <= on_t
        prob += p_t <= max_kw * on_t
        prob += p_t <= p_fix + big_m * pf_t
        prob += p_t >= p_fix - big_m * pf_t
        prob += p_t <= pv_est + big_m * (1 - pf_t)
        prob += p_t >= pv_est - big_m * (1 - pf_t)
        prob += p_fix <= max_kw * on_t
        if min_kw > 1e-9:
            prob += p_fix >= min_kw * (on_t - pf_t)


def _add_consumer_power_variables(
    prob: pulp.LpProblem,
    consumer: dict,
    horizon: int,
    matrix: list[dict[str, Any]],
    consumer_on: dict[str, list],
    consumer_p: dict[str, list],
    consumer_p_fixed: dict[str, list],
    consumer_pv_follow: dict[str, list],
    remaining_kwh: float,
    eauto_milp_params: dict[str, float] | None,
) -> None:
    cid = consumer["id"]
    consumer_on[cid] = [
        pulp.LpVariable(f"{cid}_on_{t}", cat=pulp.LpBinary)
        for t in range(horizon)
    ]
    add_min_on_time_constraints(
        prob,
        consumer_on[cid],
        consumer["min_on_quarterhours"],
        cid,
    )
    if not milp_uses_power_setpoint(
        consumer, matrix, remaining_kwh, eauto_milp_params
    ):
        return
    _add_setpoint_power_variables(
        prob,
        consumer,
        horizon,
        matrix,
        consumer_on,
        consumer_p,
        consumer_p_fixed,
        consumer_pv_follow,
    )


def _build_milp_model(
    matrix: list[dict[str, Any]],
    horizon: int,
    battery_params: dict,
    current_soc: float,
    planned_consumers: list,
    fixed_flex_kw_t0: float,
    remaining_by_consumer: dict[str, float],
    eauto_milp_params: dict[str, float] | None,
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
    for consumer in planned_consumers:
        cid = consumer["id"]
        rem = remaining_by_consumer.get(cid, 0.0)
        consumer_milp_charge_kw[cid] = milp_binary_charge_kw(
            consumer, matrix, rem, eauto_milp_params
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
            eauto_milp_params,
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
    eauto_milp_params: dict[str, float] | None,
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
    if eauto_milp_params and "eauto" in model.consumer_on:
        on_vars = model.consumer_on["eauto"]
        eps_on = eauto_milp_params["tie_break_on_epsilon"]
        eps_time = eauto_milp_params["tie_break_time_epsilon"]
        tie_break = eps_on * pulp.lpSum(on_vars) + eps_time * pulp.lpSum(
            t * on_vars[t] for t in range(len(on_vars))
        )
    model.prob += energy_cost + wear_cost + tie_break


def _add_consumer_delivery_constraints(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    remaining: dict[str, float],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
    verbose: bool,
    *,
    include_urgent_deadline_constraint: bool = True,
) -> None:
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        target = remaining.get(cid, 0.0)
        if target <= 0:
            continue
        ctx = charging_contexts.get(cid)
        consumer_indices = schedule_indices_for_consumer(
            matrix, model.horizon, schedule_indices, consumer, ctx
        )
        eligible = apply_charging_window_constraints(
            model.prob,
            model.consumer_on,
            matrix[: model.horizon],
            consumer,
            consumer_indices,
            ctx,
            model.consumer_p,
            model.consumer_pv_follow,
        )
        if not eligible:
            if verbose:
                logger.warning(
                    "%s: Kein zulässiges Ladezeitfenster im Horizont – Flex-Laden übersprungen.",
                    consumer["name"],
                )
            continue
        _, max_kw = power_limits_kw(consumer)
        max_deliverable = _max_deliverable_kwh(consumer, eligible)
        effective_target = min(target, max_deliverable)
        model.prob += _delivery_energy_expr(model, consumer, eligible) >= effective_target

        deadline = ctx.get("deadline") if ctx else None
        if (
            include_urgent_deadline_constraint
            and isinstance(deadline, datetime)
            and effective_target > 1e-6
        ):
            urgent = urgent_charging_indices(
                matrix[: model.horizon],
                eligible,
                deadline,
                effective_target,
                max_kw,
            )
            if urgent:
                model.prob += (
                    _delivery_energy_expr(model, consumer, urgent) >= effective_target
                )


def _var_value_at_zero(variables: list) -> float:
    value = variables[0].varValue
    return value if value is not None else 0.0


def _extract_milp_plan(model: MilpHorizonModel) -> dict[str, float]:
    return {
        "p_grid_buy": _var_value_at_zero(model.p_grid_buy),
        "p_grid_sell": _var_value_at_zero(model.p_grid_sell),
        "p_charge": _var_value_at_zero(model.p_charge),
        "p_discharge": _var_value_at_zero(model.p_discharge),
    }


def _consumer_pv_follow_now(model: MilpHorizonModel, consumer: dict) -> int:
    cid = consumer["id"]
    if not uses_pv_follow(consumer) or cid not in model.consumer_pv_follow:
        return 0
    value = model.consumer_pv_follow[cid][0].varValue
    return 1 if value is not None and value > 0.5 else 0


def _consumer_pv_follow_now_all(model: MilpHorizonModel) -> dict[str, int]:
    result: dict[str, int] = {}
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        result[cid] = _consumer_pv_follow_now(model, consumer)
    return result


def _consumer_power_now(model: MilpHorizonModel, consumer: dict) -> float:
    cid = consumer["id"]
    if cid in model.consumer_p:
        value = model.consumer_p[cid][0].varValue
        return max(0.0, float(value)) if value is not None else 0.0
    on_val = model.consumer_on[cid][0].varValue
    if on_val is not None and on_val > 0.5:
        return float(model.consumer_milp_charge_kw[cid])
    return 0.0


def _consumer_powers_now(model: MilpHorizonModel) -> tuple[dict[str, float], float]:
    consumer_powers: dict[str, float] = {}
    total_flex_power = 0.0
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        power = round(_consumer_power_now(model, consumer), 3)
        consumer_powers[cid] = power
        total_flex_power += power
    return consumer_powers, total_flex_power


def _planned_consumer_kwh(model: MilpHorizonModel, consumer: dict) -> float:
    return _planned_consumer_kwh_in_slots(
        model, consumer, list(range(model.horizon))
    )


def _planned_consumer_kwh_in_slots(
    model: MilpHorizonModel,
    consumer: dict,
    slot_indices: list[int],
) -> float:
    cid = consumer["id"]
    total = 0.0
    charge_kw = model.consumer_milp_charge_kw[cid]
    for t in slot_indices:
        if cid in model.consumer_p:
            value = model.consumer_p[cid][t].varValue
            if value is not None:
                total += float(value)
            continue
        on_val = model.consumer_on[cid][t].varValue
        if on_val is not None and on_val > 0.5:
            total += charge_kw
    return total


def _collect_urgent_rule_observability(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    remaining: dict[str, float],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
) -> dict[str, dict]:
    """Ermittelt pro Verbraucher, ob die urgent-Nebenbedingung den Plan beeinflusst."""
    observability: dict[str, dict] = {}
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        target = remaining.get(cid, 0.0)
        if target <= 0:
            continue
        ctx = charging_contexts.get(cid) or {}
        deadline = ctx.get("deadline")
        if not isinstance(deadline, datetime):
            continue
        consumer_indices = schedule_indices_for_consumer(
            matrix, model.horizon, schedule_indices, consumer, ctx
        )
        eligible = consumer_charging_eligible_indices(
            matrix[: model.horizon],
            consumer,
            consumer_indices,
            ctx,
        )
        if not eligible:
            continue
        _, max_kw = power_limits_kw(consumer)
        max_deliverable = _max_deliverable_kwh(consumer, eligible)
        effective_target = min(target, max_deliverable)
        pre_urgent, urgent = split_eligible_by_urgent_deadline(
            matrix[: model.horizon],
            eligible,
            deadline,
            effective_target,
            max_kw,
        )
        if not urgent:
            continue
        must_start = latest_start_datetime(deadline, effective_target, max_kw)
        observability[cid] = summarize_urgent_rule_usage(
            pre_urgent_indices=pre_urgent,
            urgent_indices=urgent,
            effective_target_kwh=effective_target,
            planned_pre_urgent_kwh=_planned_consumer_kwh_in_slots(
                model, consumer, pre_urgent
            ),
            planned_urgent_kwh=_planned_consumer_kwh_in_slots(model, consumer, urgent),
            deadline=deadline,
            must_start=must_start,
        )
    return observability


def _log_urgent_rule_observability(observability: dict[str, dict]) -> None:
    for cid, summary in observability.items():
        role = summary.get("role")
        if role == "nicht_aktiv":
            continue
        logger.info(
            "urgent-Regel [%s]: %s — Ziel %.3f kWh, optional geplant %.3f kWh, "
            "urgent geplant %.3f kWh (must_start=%s, deadline=%s)",
            cid,
            role,
            summary.get("target_kwh", 0.0),
            summary.get("planned_pre_urgent_kwh", 0.0),
            summary.get("planned_urgent_kwh", 0.0),
            summary.get("must_start", "?"),
            summary.get("deadline", "?"),
        )


def _derive_control_from_milp(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    milp_plan: dict[str, float],
    consumer_powers: dict[str, float],
    total_flex_power: float,
    current_soc: float,
    battery_params: dict,
) -> tuple[int, float, float]:
    min_soc = battery_params["min_soc"]
    max_soc = battery_params["max_soc"]
    max_power = battery_params["max_power_kw"]
    battery_capacity = battery_params["battery_capacity_kwh"]
    efficiency = battery_params["efficiency"]

    opt_charge = milp_plan["p_charge"]
    opt_discharge = milp_plan["p_discharge"]
    opt_grid_buy = milp_plan["p_grid_buy"]
    p_pv_0 = matrix[0]["expected_p_pv"]
    p_con_0 = matrix[0]["expected_p_act"]
    net_pv_surplus = p_pv_0 - p_con_0 - total_flex_power
    planned_soc = round(
        max(
            min_soc,
            min(max_soc, (model.e_batt[0].varValue / battery_capacity) * 100.0),
        ),
        1,
    )

    mode = bat.MODE_AUTOMATIK
    target_power = 0.0
    target_soc = 99.0
    threshold = bat.power_threshold_kw(max_power)

    if opt_charge > threshold and opt_grid_buy > threshold:
        mode = bat.MODE_ZWANGS_LADEN
        target_soc = round(max(current_soc, planned_soc), 1)
        target_power = bat.charge_kw_for_hourly_soc(
            current_soc,
            target_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
        )
    elif opt_discharge > threshold:
        candidate_soc = round(min(current_soc, planned_soc), 1)
        candidate_power = bat.discharge_kw_for_hourly_soc(
            current_soc,
            candidate_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
        )
        automatik_power = bat.automatik_discharge_kw(net_pv_surplus, max_power)
        if candidate_power > automatik_power + threshold:
            mode = bat.MODE_ZWANGS_ENTLADEN
            target_soc = candidate_soc
            target_power = candidate_power
    elif (
        net_pv_surplus < -threshold
        and opt_discharge < threshold
        and current_soc > (min_soc + 2.0)
    ):
        mode = bat.MODE_ENTLADESPERRE
        target_power = 0.0
        target_soc = 100.0

    return mode, target_power, target_soc


def _log_milp_decision(
    current_hour: int,
    matrix: list[dict[str, Any]],
    current_soc: float,
    milp_plan: dict[str, float],
    model: MilpHorizonModel,
    remaining: dict[str, float],
    consumer_powers: dict[str, float],
    consumer_pv_follow: dict[str, int],
    mode: int,
    target_power: float,
    target_soc: float,
) -> None:
    opt_charge = milp_plan["p_charge"]
    opt_discharge = milp_plan["p_discharge"]
    opt_grid_buy = milp_plan["p_grid_buy"]
    logger.info(
        "MILP-Entscheidung %s:00 | Preis=%.2f ct | SoC=%.1f%% | "
        "Ladung=%.2f kW | Entladung=%.2f kW | Netzbezug=%.2f kW",
        current_hour,
        matrix[0]["k_act"],
        current_soc,
        opt_charge,
        opt_discharge,
        opt_grid_buy,
    )
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        power_now = consumer_powers.get(cid, 0.0)
        planned_kwh = _planned_consumer_kwh(model, consumer)
        pv_flag = consumer_pv_follow.get(cid, 0)
        mode_txt = f" pv_follow={pv_flag}" if uses_pv_follow(consumer) else ""
        logger.info(
            "MILP %s: jetzt=%s (%.2f kW)%s | Restziel=%.2f kWh | "
            "geplant=%.2f kWh | min_on=%s x 15min",
            consumer["name"],
            "AN" if power_now > 0 else "AUS",
            power_now,
            mode_txt,
            remaining.get(cid, 0.0),
            planned_kwh,
            consumer["min_on_quarterhours"],
        )
    modi_text = {
        bat.MODE_AUTOMATIK: "AUTOMATIK",
        bat.MODE_ZWANGS_LADEN: "ZWANGSLADEN",
        bat.MODE_ENTLADESPERRE: "ENTLADESPERRE",
        bat.MODE_ZWANGS_ENTLADEN: "ZWANGSENTLADEN",
    }
    logger.info(
        "MILP Steuerbefehl: %s (Leistung=%.2f kW, Ziel-SoC=%.1f%%)",
        modi_text[mode],
        target_power,
        target_soc,
    )


def milp_optimizer(
    matrix: list[dict[str, Any]],
    current_hour: int,
    current_soc: float,
    battery_params: dict | None = None,
    k_push: float | None = None,
    verbose: bool = True,
    consumers: list | None = None,
    consumer_remaining_kwh: dict[str, float] | None = None,
    spa_cfg: dict | None = None,
    spa_remaining_kwh: float | None = None,
    flex_indices: list[int] | None = None,
    charging_contexts: dict[str, dict] | None = None,
    terminal_soc_percent: float | None = None,
    sunrise_soc_min_index: int | None = None,
) -> tuple[int, float, float, dict[str, float], dict[str, int], dict[str, float]]:
    """
    Berechnet den optimalen Betriebsmodus und die Ziel-Leistung für den Loxone Miniserver.
    Optimiert Batterie und alle konfigurierten flexible_consumers gemeinsam per MILP.
    Rückgabe: (mode, target_power, target_soc, {consumer_id: leistung_kw},
               {consumer_id: pv_follow 0|1}, milp_plan)
    """
    if not matrix:
        logger.error("MILP: Optimierungsmatrix ist leer.")
        return _AUTOMATIK_FALLBACK

    battery_params = battery_params or config.get_battery_params()
    fallback_k_push = k_push if k_push is not None else config.get_push_price_cent()
    active = _active_consumers(consumers)
    remaining = _remaining_kwh_by_consumer(active, consumer_remaining_kwh, spa_remaining_kwh)

    horizon = len(matrix)
    day_indices = _day_indices(matrix, horizon)
    schedule_indices = flex_indices if flex_indices is not None else day_indices
    contexts = charging_contexts or {}
    planned_consumers = filter_feasible_consumers(
        active,
        remaining,
        matrix[:horizon],
        schedule_indices,
        verbose,
        contexts,
    )
    has_eauto = any(c.get("id") == "eauto" for c in planned_consumers)
    eauto_milp_params = config.get_eauto_milp_params() if has_eauto else None
    preset_powers, milp_consumers = split_eauto_preset(
        planned_consumers,
        matrix[:horizon],
        remaining,
        schedule_indices,
        contexts,
        eauto_milp_params,
    )
    fixed_flex_kw_t0 = sum(preset_powers.values())

    model = _build_milp_model(
        matrix,
        horizon,
        battery_params,
        current_soc,
        milp_consumers,
        fixed_flex_kw_t0,
        remaining,
        eauto_milp_params,
    )
    wear_cent_per_kwh = config.get_battery_wear_cent_per_kwh(
        battery_params["battery_capacity_kwh"]
    )
    _add_milp_objective(
        model,
        matrix,
        fallback_k_push,
        eauto_milp_params,
        wear_cent_per_kwh=wear_cent_per_kwh,
    )
    logged_simulation = bool(
        matrix and matrix[0].get("consumption_mode") == "logged_day"
    )
    _add_consumer_delivery_constraints(
        model,
        matrix,
        remaining,
        schedule_indices,
        contexts,
        verbose,
        include_urgent_deadline_constraint=not logged_simulation,
    )
    if sunrise_soc_min_index is not None:
        e_min = (battery_params["min_soc"] / 100.0) * battery_params["battery_capacity_kwh"]
        _add_sunrise_soc_min_constraint(model, sunrise_soc_min_index, e_min)
        if verbose:
            logger.info(
                "MILP SOC-Anker Sonnenaufgang: Slot %d = %.1f %%",
                sunrise_soc_min_index,
                battery_params["min_soc"],
            )
    elif e_terminal := _terminal_soc_energy_kwh(battery_params, terminal_soc_percent):
        _add_terminal_soc_constraint(model, e_terminal)
        if verbose:
            logger.info(
                "MILP End-SoC-Randbedingung: %.1f %% (aktuell %.1f %%)",
                terminal_soc_percent,
                current_soc,
            )

    update_cbc_milp_context_from_row(matrix[0])
    status = solve_with_strict_fallback(model.prob, msg=False, verbose=verbose)
    if status != "Optimal":
        record_cbc_event("milp_no_optimal", final_status=status)
        return _AUTOMATIK_FALLBACK

    milp_plan = _extract_milp_plan(model)
    consumer_powers, total_flex_power = _consumer_powers_now(model)
    consumer_powers.update(preset_powers)
    total_flex_power += sum(preset_powers.values())
    consumer_pv_follow = _consumer_pv_follow_now_all(model)
    mode, target_power, target_soc = _derive_control_from_milp(
        model,
        matrix,
        milp_plan,
        consumer_powers,
        total_flex_power,
        current_soc,
        battery_params,
    )

    urgent_observability = _collect_urgent_rule_observability(
        model,
        matrix,
        remaining,
        schedule_indices,
        contexts,
    )
    _log_urgent_rule_observability(urgent_observability)

    if verbose:
        _log_milp_decision(
            current_hour,
            matrix,
            current_soc,
            milp_plan,
            model,
            remaining,
            consumer_powers,
            consumer_pv_follow,
            mode,
            target_power,
            target_soc,
        )

    return (
        mode,
        target_power,
        target_soc,
        consumer_powers,
        consumer_pv_follow,
        milp_plan,
        urgent_observability,
    )
