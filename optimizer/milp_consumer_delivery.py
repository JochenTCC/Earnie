"""MILP consumer delivery feasibility, urgent ASAP, diagnostics."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pulp

from .charging_context import (
    asap_indices_for_urgent_min,
    charging_schedule_enabled,
    latest_start_datetime,
    schedule_indices_for_consumer,
    split_eligible_by_urgent_deadline,
    summarize_urgent_rule_usage,
)
from .consumer_power import power_limits_kw, uses_pv_follow
from .eauto_milp import milp_uses_power_setpoint
from .filter_context import (
    apply_slot_availability_constraints,
    consumer_flex_eligible_indices,
)
from .generic_flex_context import (
    consumer_generic_eligible_indices,
    generic_flex_window,
)
from .milp_consumer_vars import (
    _min_on_hours,
    _planned_consumer_kwh_in_slots,
)
from .thermal_flex_context import is_thermal_flex_consumer
from .slot_duration import DEFAULT_DT_H

if TYPE_CHECKING:
    from .milp_horizon import MilpHorizonModel

logger = logging.getLogger(__name__)

def _max_deliverable_kwh(
    consumer: dict,
    eligible_indices: list[int],
    *,
    dt_h: float,
) -> float:
    _, max_kw = power_limits_kw(consumer)
    return len(eligible_indices) * max_kw * float(dt_h)


def _eligible_slot_labels(matrix: list, eligible_indices: list[int]) -> list[str]:
    from .charging_context import matrix_slot_datetime

    labels: list[str] = []
    for index in eligible_indices:
        if 0 <= index < len(matrix):
            labels.append(matrix_slot_datetime(matrix, index).strftime("%m-%d %H:%M"))
    return labels


def _diagnostics_planned_entry(
    consumer: dict,
    *,
    matrix: list,
    horizon: int,
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
    filters: dict[str, dict],
    target: float,
    base_entry: dict,
) -> dict:
    """Fill delivery-diagnostics fields for a planned consumer with target > 0."""
    cid = consumer["id"]
    entry = dict(base_entry)
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
    max_deliverable = _max_deliverable_kwh(
        consumer, eligible, dt_h=DEFAULT_DT_H
    )
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
    return entry


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
        result[cid] = _diagnostics_planned_entry(
            consumer,
            matrix=matrix,
            horizon=horizon,
            schedule_indices=schedule_indices,
            charging_contexts=charging_contexts,
            filters=filters,
            target=target,
            base_entry=entry,
        )
    return result


def _delivery_energy_expr(
    model: MilpHorizonModel,
    consumer: dict,
    eligible_indices: list[int],
):
    cid = consumer["id"]
    dt_h = float(model.dt_h)
    if cid in model.consumer_p:
        return pulp.lpSum(model.consumer_p[cid][t] for t in eligible_indices) * dt_h
    charge_kw = model.consumer_milp_charge_kw[cid]
    return (
        pulp.lpSum(
            charge_kw * model.consumer_on[cid][t]
            for t in eligible_indices
        )
        * dt_h
    )


def filter_feasible_consumers(
    consumers: list,
    remaining_kwh: dict[str, float],
    matrix: list,
    schedule_indices: list[int],
    verbose: bool,
    charging_contexts: dict[str, dict] | None,
    filter_contexts: dict[str, dict] | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> list:
    """Entfernt Verbraucher, deren Ziel im verbleibenden Horizont nicht erreichbar ist."""
    from .slot_duration import validate_dt_h

    dt_h = validate_dt_h(dt_h)
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
        max_deliverable = _max_deliverable_kwh(
            consumer, capacity_indices, dt_h=dt_h
        )
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


def _parse_charging_deadline(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def _add_urgent_min_asap_constraint(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    consumer: dict,
    ctx: dict | None,
    *,
    max_kw: float,
) -> None:
    """Hard ASAP delivery for SOC-Min-Immediate floor (independent of weekday window)."""
    urgent_min = float((ctx or {}).get("urgent_min_kwh") or 0.0)
    if urgent_min <= 1e-9 or max_kw <= 1e-9:
        return
    deadline = _parse_charging_deadline((ctx or {}).get("deadline"))
    asap = asap_indices_for_urgent_min(
        matrix,
        horizon=model.horizon,
        urgent_min_kwh=urgent_min,
        max_kw=max_kw,
        deadline=deadline,
    )
    if not asap:
        return
    effective_urgent = min(
        urgent_min, _max_deliverable_kwh(consumer, asap, dt_h=model.dt_h)
    )
    if effective_urgent <= 1e-9:
        return
    model.prob += _delivery_energy_expr(model, consumer, asap) >= effective_urgent


def _resolve_delivery_eligible_indices(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    consumer: dict,
    schedule_indices: list[int],
    ctx: dict | None,
    filters: dict[str, dict],
) -> list[int]:
    cid = consumer["id"]
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
    return apply_slot_availability_constraints(
        model.prob,
        model.consumer_on,
        consumer,
        consumer_indices,
        eligible,
        model.consumer_p,
        model.consumer_pv_follow,
    )


def _add_one_consumer_delivery_constraints(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    consumer: dict,
    remaining: dict[str, float],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
    filters: dict[str, dict],
    verbose: bool,
) -> None:
    cid = consumer["id"]
    target = remaining.get(cid, 0.0)
    if target <= 0:
        return
    ctx = charging_contexts.get(cid)
    eligible = _resolve_delivery_eligible_indices(
        model, matrix, consumer, schedule_indices, ctx, filters
    )
    if not eligible:
        if verbose:
            logger.warning(
                "%s: Kein zulässiges Ladezeitfenster im Horizont – Flex-Laden übersprungen.",
                consumer["name"],
            )
        return
    _, max_kw = power_limits_kw(consumer)
    max_deliverable = _max_deliverable_kwh(
        consumer, eligible, dt_h=model.dt_h
    )
    effective_target = min(target, max_deliverable)
    model.prob += _delivery_energy_expr(model, consumer, eligible) >= effective_target
    _add_urgent_min_asap_constraint(
        model,
        matrix,
        consumer,
        ctx,
        max_kw=max_kw,
    )


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
        if is_thermal_flex_consumer(consumer):
            continue
        _add_one_consumer_delivery_constraints(
            model,
            matrix,
            consumer,
            remaining,
            schedule_indices,
            charging_contexts,
            filters,
            verbose,
        )


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
        max_deliverable = _max_deliverable_kwh(
            consumer, eligible, dt_h=model.dt_h
        )
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
        logger.debug(
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
