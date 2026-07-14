"""MILP-Verbraucher: Variablen, Liefer-Nebenbedingungen, Ergebnis-Extraktion."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pulp

from .charging_context import (
    latest_start_datetime,
    schedule_indices_for_consumer,
    split_eligible_by_urgent_deadline,
    summarize_urgent_rule_usage,
    charging_schedule_enabled,
)
from .consumer_power import (
    estimate_pv_surplus_kw,
    power_limits_kw,
    uses_pv_follow,
)
from .eauto_milp import milp_uses_power_setpoint
from .filter_context import (
    apply_slot_availability_constraints,
    consumer_flex_eligible_indices,
)
from .generic_flex_context import (
    consumer_generic_eligible_indices,
    generic_flex_window,
)
from .thermal_flex_context import is_thermal_flex_consumer

if TYPE_CHECKING:
    from .milp_horizon import MilpHorizonModel

logger = logging.getLogger(__name__)


def add_min_on_time_constraints(
    prob: pulp.LpProblem,
    on_vars: list,
    min_on_quarterhours: int,
    prefix: str,
    *,
    on_before_horizon: bool = False,
    force_on_at_start: bool = False,
) -> None:
    """Erzwingt Mindest-Einschaltdauer; MILP arbeitet stündlich (4 Viertelstunden = 1 Slot)."""
    min_hours = max(1, (int(min_on_quarterhours) + 3) // 4)
    if force_on_at_start and on_vars:
        prob += on_vars[0] == 1
    if min_hours <= 1:
        return
    horizon = len(on_vars)
    prev_at_start = 1 if on_before_horizon else 0
    for t in range(horizon - min_hours + 1):
        if t == 0:
            if on_before_horizon:
                continue
            prev: pulp.LpAffineExpression | int = prev_at_start
        else:
            prev = on_vars[t - 1]
        prob += pulp.lpSum(on_vars[t:t + min_hours]) >= min_hours * (on_vars[t] - prev)


def add_generic_block_start_guard(
    prob: pulp.LpProblem,
    on_vars: list,
    eligible_indices: list[int],
    min_hours: int,
    *,
    continuing: bool,
) -> None:
    """Verhindert neuen Block-Start an t=0 ohne min_on zusammenhängende eligible Slots."""
    if continuing or min_hours <= 1 or not on_vars:
        return
    eligible_set = set(eligible_indices)
    if 0 not in eligible_set:
        prob += on_vars[0] == 0
        return
    if not all(slot in eligible_set for slot in range(min_hours)):
        prob += on_vars[0] == 0


def _max_deliverable_kwh(consumer: dict, eligible_indices: list[int]) -> float:
    _, max_kw = power_limits_kw(consumer)
    return len(eligible_indices) * max_kw


def _min_on_hours(consumer: dict) -> int:
    min_on_qh = int(consumer.get("min_on_quarterhours", 4) or 4)
    return max(1, (min_on_qh + 3) // 4)


def _eligible_slot_labels(matrix: list, eligible_indices: list[int]) -> list[str]:
    from .charging_context import matrix_slot_datetime

    labels: list[str] = []
    for index in eligible_indices:
        if 0 <= index < len(matrix):
            labels.append(matrix_slot_datetime(matrix, index).strftime("%m-%d %H:%M"))
    return labels


def delivery_constraint_diagnostics(
    matrix: list,
    remaining: dict[str, float],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
    consumers: list,
    filter_contexts: dict[str, dict] | None = None,
    verbose: bool = False,
) -> dict[str, dict]:
    """Liefer-Nebenbedingungen je Verbraucher (ohne MILP-Lösung)."""
    filters = filter_contexts or {}
    horizon = len(matrix)
    planned = filter_feasible_consumers(
        consumers,
        remaining,
        matrix[:horizon],
        schedule_indices,
        verbose,
        charging_contexts,
        filters,
    )
    planned_ids = {consumer["id"] for consumer in planned}
    result: dict[str, dict] = {}

    for consumer in consumers:
        cid = consumer["id"]
        target = float(remaining.get(cid, 0.0) or 0.0)
        entry: dict = {
            "planned": cid in planned_ids,
            "remaining_kwh": round(target, 3),
            "min_on_hours": _min_on_hours(consumer),
            "generic_flex": generic_flex_window(consumer) is not None,
        }
        if target <= 0 or cid not in planned_ids:
            result[cid] = entry
            continue

        ctx = charging_contexts.get(cid)
        consumer_indices = schedule_indices_for_consumer(
            matrix, horizon, schedule_indices, consumer, ctx
        )
        eligible = consumer_flex_eligible_indices(
            matrix[:horizon],
            consumer,
            consumer_indices,
            ctx,
            filters.get(cid),
        )
        if generic_flex_window(consumer):
            generic_eligible = set(
                consumer_generic_eligible_indices(
                    matrix[:horizon],
                    consumer,
                    consumer_indices,
                )
            )
            eligible = [index for index in eligible if index in generic_eligible]
        _, max_kw = power_limits_kw(consumer)
        max_deliverable = _max_deliverable_kwh(consumer, eligible)
        effective_target = min(target, max_deliverable)
        entry.update(
            {
                "eligible_count": len(eligible),
                "eligible_slots": _eligible_slot_labels(matrix, eligible),
                "max_kw": round(float(max_kw), 3),
                "max_deliverable_kwh": round(max_deliverable, 3),
                "effective_target_kwh": round(effective_target, 3),
                "target_gap_kwh": round(target - effective_target, 3),
            }
        )
        result[cid] = entry
    return result


def add_generic_flex_rolling_constraints(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
    consumer_continue_on: dict[str, bool] | None,
    *,
    filter_contexts: dict[str, dict] | None = None,
) -> None:
    """Rolling-Horizont: min_on-Fortsetzung und Start-Sperre für generic-Flex."""
    filters = filter_contexts or {}
    continue_on = consumer_continue_on or {}
    for consumer in model.planned_consumers:
        if not generic_flex_window(consumer):
            continue
        cid = consumer["id"]
        continuing = bool(continue_on.get(cid, False))
        min_hours = _min_on_hours(consumer)
        ctx = charging_contexts.get(cid)
        consumer_indices = schedule_indices_for_consumer(
            matrix, model.horizon, schedule_indices, consumer, ctx
        )
        eligible = consumer_flex_eligible_indices(
            matrix[: model.horizon],
            consumer,
            consumer_indices,
            ctx,
            filters.get(cid),
        )
        generic_eligible = set(
            consumer_generic_eligible_indices(
                matrix[: model.horizon],
                consumer,
                consumer_indices,
            )
        )
        eligible = [index for index in eligible if index in generic_eligible]
        add_generic_block_start_guard(
            model.prob,
            model.consumer_on[cid],
            eligible,
            min_hours,
            continuing=continuing,
        )


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
    filter_contexts: dict[str, dict] | None = None,
) -> list:
    """Entfernt Verbraucher, deren Ziel im verbleibenden Horizont nicht erreichbar ist."""
    feasible = []
    contexts = charging_contexts or {}
    filters = filter_contexts or {}
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
        eligible = consumer_flex_eligible_indices(
            matrix, consumer, consumer_indices, ctx, filters.get(cid)
        )
        capacity_indices = eligible if eligible else consumer_indices
        max_deliverable = _max_deliverable_kwh(consumer, capacity_indices)
        if target > max_deliverable + 1e-6:
            if verbose:
                sched_hint = ""
                if charging_schedule_enabled(consumer):
                    sched_hint = f" ({len(eligible)} h im Ladezeitfenster)"
                elif filters.get(cid, {}).get("blocked_indices"):
                    sched_hint = (
                        f" ({len(eligible)} h außerhalb nativem Filterfenster)"
                    )
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
    *,
    continue_on: bool = False,
) -> None:
    cid = consumer["id"]
    consumer_on[cid] = [
        pulp.LpVariable(f"{cid}_on_{t}", cat=pulp.LpBinary)
        for t in range(horizon)
    ]
    generic_continuing = continue_on and generic_flex_window(consumer) is not None
    add_min_on_time_constraints(
        prob,
        consumer_on[cid],
        consumer["min_on_quarterhours"],
        cid,
        on_before_horizon=generic_continuing,
        force_on_at_start=generic_continuing,
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


def _parse_charging_deadline(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def _add_consumer_delivery_constraints(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    remaining: dict[str, float],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
    verbose: bool,
    *,
    filter_contexts: dict[str, dict] | None = None,
) -> None:
    filters = filter_contexts or {}
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        if is_thermal_flex_consumer(consumer):
            continue
        target = remaining.get(cid, 0.0)
        if target <= 0:
            continue
        ctx = charging_contexts.get(cid)
        consumer_indices = schedule_indices_for_consumer(
            matrix, model.horizon, schedule_indices, consumer, ctx
        )
        eligible = consumer_flex_eligible_indices(
            matrix[: model.horizon],
            consumer,
            consumer_indices,
            ctx,
            filters.get(cid),
        )
        if generic_flex_window(consumer):
            generic_eligible = set(
                consumer_generic_eligible_indices(
                    matrix[: model.horizon],
                    consumer,
                    consumer_indices,
                )
            )
            eligible = [index for index in eligible if index in generic_eligible]
        eligible = apply_slot_availability_constraints(
            model.prob,
            model.consumer_on,
            consumer,
            consumer_indices,
            eligible,
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
    filter_contexts: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Ermittelt pro Verbraucher, ob die urgent-Nebenbedingung den Plan beeinflusst."""
    filters = filter_contexts or {}
    observability: dict[str, dict] = {}
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        target = remaining.get(cid, 0.0)
        if target <= 0:
            continue
        ctx = charging_contexts.get(cid) or {}
        deadline = _parse_charging_deadline(ctx.get("deadline"))
        if deadline is None:
            continue
        consumer_indices = schedule_indices_for_consumer(
            matrix, model.horizon, schedule_indices, consumer, ctx
        )
        eligible = consumer_flex_eligible_indices(
            matrix[: model.horizon],
            consumer,
            consumer_indices,
            ctx,
            filters.get(cid),
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
        if not pre_urgent and not urgent:
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
