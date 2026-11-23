"""Thermal flex MILP constraints: day delivery, pulse limits, rods.

Split from ``thermal_flex_context`` (import facade).
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from optimizer.hp_store import HP_STORE_CONTEXT_KEY
from optimizer.rod_store import STORE_BALANCE_CONTEXT_KEY
from optimizer.thermal_flex_base import (
    LIVE_STORE_PLAN_KEY,
    _force_thermal_on_slots,
    _indices_for_date,
    _max_on_hours,
    _max_on_slots_with_limits,
    _max_pulses_per_day,
    _prorate_thermal_day_target_kwh,
    _rod_energy_expr,
    add_max_on_duration_constraints,
    add_max_pulses_per_day_constraints,
    consumer_thermal_eligible_indices,
    is_heating_rod_consumer,
    is_thermal_flex_consumer,
)
from optimizer.thermal_flex_store import (
    _add_fuel_parent_rod_caps,
    _add_hp_store_balance,
    _add_live_store_consumer,
    _add_rod_store_balance,
)

if TYPE_CHECKING:
    from optimizer.milp_horizon import MilpHorizonModel


def add_thermal_flex_constraints(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    thermal_contexts: dict[str, dict],
    *,
    consumer_continue_on: dict[str, bool] | None = None,
) -> None:
    """Tages-Lieferung, max. Pulsdauer und max. Pulse/Tag für thermal_annual."""
    continue_on = consumer_continue_on or {}

    def running_day(consumer_id: str) -> date | None:
        # Already running = ON before the plan's first slot: exempts only that day's first block.
        return matrix[0]["date"] if continue_on.get(consumer_id, False) and matrix else None

    rods = [c for c in model.planned_consumers if is_heating_rod_consumer(c)]
    covered: dict[str, set[int]] = {str(rod["id"]): set() for rod in rods}
    for consumer in model.planned_consumers:
        if not is_thermal_flex_consumer(consumer):
            continue
        _add_heat_source_constraints(
            model,
            matrix,
            schedule_indices,
            consumer,
            _context(thermal_contexts, consumer["id"]),
            running_day=running_day(consumer["id"]),
            rods=[rod for rod in rods if rod["parent_id"] == consumer["id"]],
            rod_covered=covered,
        )
    for rod in rods:
        _add_rod_constraints(
            model,
            matrix,
            schedule_indices,
            rod,
            _context(thermal_contexts, rod["id"]),
            covered[str(rod["id"])],
            running_day=running_day(rod["id"]),
        )


def _context(thermal_contexts: dict[str, dict], consumer_id: str) -> dict:
    return thermal_contexts.get(consumer_id) or {}


def _add_heat_source_constraints(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    consumer: dict,
    ctx: dict,
    *,
    running_day: date | None,
    rods: list[dict],
    rod_covered: dict[str, set[int]],
) -> None:
    """One thermal_annual consumer: Live store level, or day delivery plus the SE store balance."""
    if ctx.get(LIVE_STORE_PLAN_KEY) is not None:
        _add_live_store_consumer(
            model,
            matrix,
            schedule_indices,
            consumer,
            ctx,
            running_day=running_day,
            rods=rods,
            rod_covered=rod_covered,
        )
        return
    effective_by_day = _add_one_thermal_flex_consumer(
        model,
        matrix,
        schedule_indices,
        consumer,
        ctx,
        running_day=running_day,
        rods=rods,
        rod_covered=rod_covered,
    )
    hp_balance = ctx.get(HP_STORE_CONTEXT_KEY)
    if hp_balance is not None:
        _add_hp_store_balance(
            model, matrix, schedule_indices, consumer, hp_balance, rods, effective_by_day
        )


def _add_rod_constraints(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    rod: dict,
    ctx: dict,
    covered: set[int],
    *,
    running_day: date | None,
) -> None:
    """One heating rod: fuel-parent cap, store balance, off outside its slots, Live pulse limit."""
    if not rod["parent_heat_electric"]:
        _add_fuel_parent_rod_caps(model, matrix, schedule_indices, rod, ctx, covered)
    balance = ctx.get(STORE_BALANCE_CONTEXT_KEY)
    if balance is not None:
        _add_rod_store_balance(model, matrix, schedule_indices, rod, balance, covered)
    _force_rod_off_outside(model, rod, covered)
    if ctx.get("live_pulse_limit"):
        _add_live_rod_pulse_limit(model, matrix, rod, covered, running_day=running_day)


def _force_rod_off_outside(model: MilpHorizonModel, rod: dict, covered: set[int]) -> None:
    """No heat demand (or outside the window / book) on a slot → the rod stays off."""
    on_vars = model.consumer_on[rod["id"]]
    for index in range(len(on_vars)):
        if index not in covered:
            model.prob += (on_vars[index] == 0, f"{rod['id']}_rod_off_{index}")


def _add_live_rod_pulse_limit(
    model: MilpHorizonModel,
    matrix: list,
    rod: dict,
    covered: set[int],
    *,
    running_day: date | None,
) -> None:
    """A real rod hangs on a relay: no 15-minute flicker (SE keeps its goldens unchanged)."""
    for day in sorted({matrix[index].get("date") for index in covered}):
        add_max_pulses_per_day_constraints(
            model.prob,
            model.consumer_on[rod["id"]],
            [index for index in _indices_for_date(matrix, day) if index in covered],
            max_pulses=_max_pulses_per_day(rod),
            prefix=f"{rod['id']}_{day.isoformat()}",
            continuing=running_day is not None and day == running_day,
        )


def _thermal_day_want_kwh(
    ctx: dict,
    day: date,
    day_indices: list[int],
    daily_targets: dict[date, float],
) -> float:
    """Energy [kWh] the thermal consumer should deliver on ``day`` (before caps)."""
    slot_energy = list(ctx.get("slot_energy_kwh") or [])
    slot_aligned = bool(ctx.get("targets_slot_aligned")) and bool(slot_energy)
    if slot_aligned:
        return round(
            sum(
                float(slot_energy[index])
                for index in day_indices
                if index < len(slot_energy)
            ),
            3,
        )
    return _prorate_thermal_day_target_kwh(
        float(daily_targets.get(day, 0.0) or 0.0), len(day_indices)
    )


def _add_one_thermal_flex_consumer(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    consumer: dict,
    ctx: dict,
    *,
    running_day: date | None,
    rods: list[dict] | None = None,
    rod_covered: dict[str, set[int]] | None = None,
) -> dict[date, float]:
    """Constraints of one thermal_annual consumer; returns the energy [kWh] it must deliver per day."""
    daily_targets: dict[date, float] = dict(ctx.get("daily_targets") or {})
    forced_indices = [int(i) for i in (ctx.get("forced_indices") or [])]
    if not daily_targets and not forced_indices:
        return {}
    eligible_set = _thermal_on_setup(model, matrix, schedule_indices, consumer, forced_indices)
    day_run = {
        "ctx": ctx,
        "daily_targets": daily_targets,
        "forced": bool(forced_indices),
        "running_day": running_day,
        "rods": rods or [],
        "rod_covered": rod_covered if rod_covered is not None else {},
        "max_pulses": _max_pulses_per_day(consumer),
    }
    effective_by_day: dict[date, float] = {}
    for day in sorted(daily_targets):
        effective = _add_thermal_day(model, matrix, consumer, day, eligible_set, day_run)
        if effective > 1e-9:
            effective_by_day[day] = effective
    return effective_by_day


def _thermal_on_setup(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    consumer: dict,
    forced_indices: list[int],
) -> set[int]:
    """Max-on duration (without forced hours) and forced slots; returns the eligible slots."""
    cid = consumer["id"]
    on_vars = model.consumer_on[cid]
    if not forced_indices:
        add_max_on_duration_constraints(
            model.prob, on_vars, max_hours=_max_on_hours(consumer), prefix=cid
        )
    # Sunrise: schedule_indices are book (SA1→SA2). Spec/plausibility WP is
    # book-window energy — require delivery only on those slots, using the
    # exact slot-aligned kWh (not calendar HDD × day_slots/96).
    eligible_set = set(
        consumer_thermal_eligible_indices(matrix, consumer, schedule_indices)
    )
    _force_thermal_on_slots(model, cid, on_vars, forced_indices, eligible_set)
    return eligible_set


def _add_thermal_day(
    model: MilpHorizonModel,
    matrix: list,
    consumer: dict,
    day: date,
    eligible_set: set[int],
    run: dict,
) -> float:
    """Delivery (and pulse limit) of one day; returns the day's energy [kWh] (≤ 1e-9: none)."""
    from optimizer.milp_consumers import _delivery_energy_expr

    cid = consumer["id"]
    day_indices = [index for index in _indices_for_date(matrix, day) if index in eligible_set]
    if not day_indices:
        return 0.0
    effective = _thermal_day_effective_kwh(
        model, consumer, run["ctx"], day, day_indices, run["daily_targets"], forced=run["forced"]
    )
    if effective <= 1e-9:
        return effective
    if not run["forced"]:
        add_max_pulses_per_day_constraints(
            model.prob,
            model.consumer_on[cid],
            day_indices,
            max_pulses=run["max_pulses"],
            prefix=f"{cid}_{day.isoformat()}",
            continuing=run["running_day"] is not None and day == run["running_day"],
        )
    delivered = _add_rod_day_heat(
        model,
        matrix,
        run["rods"],
        day,
        day_indices,
        effective,
        _delivery_energy_expr(model, consumer, day_indices),
        run["rod_covered"],
    )
    model.prob += (
        delivered >= effective,
        f"{cid}_thermal_day_{day.isoformat()}",
    )
    return effective


def _thermal_day_effective_kwh(
    model: MilpHorizonModel,
    consumer: dict,
    ctx: dict,
    day: date,
    day_indices: list[int],
    daily_targets: dict[date, float],
    *,
    forced: bool,
) -> float:
    """Energy [kWh] the consumer must deliver on ``day``: the want, capped by what it can run."""
    from optimizer.consumer_power import power_limits_kw
    from optimizer.milp_consumers import _max_deliverable_kwh

    _, max_kw = power_limits_kw(consumer)
    max_deliverable = _max_deliverable_kwh(
        consumer, day_indices, dt_h=model.dt_h
    )
    want = _thermal_day_want_kwh(ctx, day, day_indices, daily_targets)
    if forced:
        op_max_kwh = max_deliverable
    else:
        op_slots = _max_on_slots_with_limits(
            len(day_indices),
            max_hours=_max_on_hours(consumer),
            max_pulses=_max_pulses_per_day(consumer),
        )
        op_max_kwh = op_slots * float(max_kw) * float(model.dt_h)
    return min(want, max_deliverable, op_max_kwh)


def _add_rod_day_heat(
    model: MilpHorizonModel,
    matrix: list,
    rods: list[dict],
    day: date,
    day_indices: list[int],
    effective: float,
    delivered,
    rod_covered: dict[str, set[int]],
):
    """Add the rods' heat to the day's delivery; each rod capped at the day's heat."""
    for rod in rods:
        # Rod heat (η = 1) replaces heat-pump electricity × JAZ; capped at the day's heat.
        eff = float(rod["parent_heat_efficiency"])
        rod_indices = [
            index
            for index in day_indices
            if index in set(consumer_thermal_eligible_indices(matrix, rod, day_indices))
        ]
        if not rod_indices:
            continue
        rod_kwh = _rod_energy_expr(model, rod, rod_indices)
        delivered = delivered + rod_kwh * (1.0 / eff)
        model.prob += (
            rod_kwh <= effective * eff,
            f"{rod['id']}_rod_cap_{day.isoformat()}",
        )
        rod_covered.setdefault(str(rod["id"]), set()).update(rod_indices)
    return delivered
