"""MILP consumer variables, min-on / rolling constraints, power extractors."""
from __future__ import annotations

from typing import Any

import pulp

from .charging_context import schedule_indices_for_consumer
from .consumer_power import (
    estimate_pv_surplus_kw,
    power_limits_kw,
    uses_pv_follow,
)
from .eauto_milp import milp_uses_power_setpoint
from .filter_context import consumer_flex_eligible_indices
from .generic_flex_context import (
    consumer_generic_eligible_indices,
    generic_flex_window,
)
from .slot_duration import DEFAULT_DT_H


def _min_on_hours(consumer: dict) -> int:
    """Minimum consecutive ON slots (config key remains min_on_quarterhours)."""
    min_on_qh = int(consumer.get("min_on_quarterhours", 4) or 4)
    return max(1, min_on_qh)


def add_min_on_time_constraints(
    prob: pulp.LpProblem,
    on_vars: list,
    min_on_quarterhours: int,
    prefix: str,
    *,
    on_before_horizon: bool = False,
    force_on_at_start: bool = False,
) -> None:
    """Enforce minimum consecutive ON slots (``min_on_quarterhours`` = real MILP slots)."""
    min_slots = max(1, int(min_on_quarterhours))
    if force_on_at_start and on_vars:
        prob += on_vars[0] == 1
    if min_slots <= 1:
        return
    horizon = len(on_vars)
    prev_at_start = 1 if on_before_horizon else 0
    for t in range(horizon - min_slots + 1):
        if t == 0:
            if on_before_horizon:
                continue
            prev: pulp.LpAffineExpression | int = prev_at_start
        else:
            prev = on_vars[t - 1]
        prob += pulp.lpSum(on_vars[t:t + min_slots]) >= min_slots * (on_vars[t] - prev)


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


def _consumer_pv_follow_at(model: MilpHorizonModel, consumer: dict, hour_index: int) -> int:
    cid = consumer["id"]
    if not uses_pv_follow(consumer) or cid not in model.consumer_pv_follow:
        return 0
    value = model.consumer_pv_follow[cid][hour_index].varValue
    return 1 if value is not None and value > 0.5 else 0


def _consumer_pv_follow_now(model: MilpHorizonModel, consumer: dict) -> int:
    return _consumer_pv_follow_at(model, consumer, 0)


def _consumer_pv_follow_at_all(
    model: MilpHorizonModel, hour_index: int
) -> dict[str, int]:
    result: dict[str, int] = {}
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        result[cid] = _consumer_pv_follow_at(model, consumer, hour_index)
    return result


def _consumer_pv_follow_now_all(model: MilpHorizonModel) -> dict[str, int]:
    return _consumer_pv_follow_at_all(model, 0)


def _consumer_power_at(
    model: MilpHorizonModel, consumer: dict, hour_index: int
) -> float:
    cid = consumer["id"]
    if cid in model.consumer_p:
        value = model.consumer_p[cid][hour_index].varValue
        return max(0.0, float(value)) if value is not None else 0.0
    on_val = model.consumer_on[cid][hour_index].varValue
    if on_val is not None and on_val > 0.5:
        return float(model.consumer_milp_charge_kw[cid])
    return 0.0


def _consumer_power_now(model: MilpHorizonModel, consumer: dict) -> float:
    return _consumer_power_at(model, consumer, 0)


def _consumer_powers_at(
    model: MilpHorizonModel, hour_index: int
) -> tuple[dict[str, float], float]:
    consumer_powers: dict[str, float] = {}
    total_flex_power = 0.0
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        power = round(_consumer_power_at(model, consumer, hour_index), 3)
        consumer_powers[cid] = power
        total_flex_power += power
    return consumer_powers, total_flex_power


def _consumer_powers_now(model: MilpHorizonModel) -> tuple[dict[str, float], float]:
    return _consumer_powers_at(model, 0)


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
    dt_h = float(model.dt_h)
    for t in slot_indices:
        if cid in model.consumer_p:
            value = model.consumer_p[cid][t].varValue
            if value is not None:
                total += float(value) * dt_h
            continue
        on_val = model.consumer_on[cid][t].varValue
        if on_val is not None and on_val > 0.5:
            total += charge_kw * dt_h
    return total
