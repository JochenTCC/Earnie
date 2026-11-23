"""Store levels of the thermal flex MILP: rod / heat-pump store balance, Live store (split
from thermal_flex_context)."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

import pulp

from optimizer.hp_store import HpStoreBalance
from optimizer.rod_store import RodStoreBalance
from optimizer.thermal_flex_base import (
    LIVE_STORE_PLAN_KEY,
    _force_thermal_on_slots,
    _indices_for_date,
    _max_pulses_per_day,
    _rod_energy_expr,
    add_max_pulses_per_day_constraints,
    consumer_thermal_eligible_indices,
)
from optimizer.thermal_store_model import add_store_level

if TYPE_CHECKING:
    from optimizer.milp_horizon import MilpHorizonModel


def _add_fuel_parent_rod_caps(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    rod: dict,
    ctx: dict,
    covered: set[int],
) -> None:
    """Live, rod beside a fuel source: rod heat (η = 1) of the first day ≤ the store's free heat."""
    caps: dict[date, float] = dict(ctx.get("daily_heat_cap_kwh") or {})
    eligible_set = set(consumer_thermal_eligible_indices(matrix, rod, schedule_indices))
    for day, cap in sorted(caps.items()):
        day_indices = [i for i in _indices_for_date(matrix, day) if i in eligible_set]
        if not day_indices or cap <= 1e-9:
            continue
        model.prob += (
            _rod_energy_expr(model, rod, day_indices) <= cap,
            f"{rod['id']}_rod_cap_{day.isoformat()}",
        )
        covered.update(day_indices)


def _add_rod_store_balance(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    rod: dict,
    balance: RodStoreBalance,
    covered: set[int],
) -> None:
    """SE: the rod's heat (η = 1) in the store stays inside the band on every slot of the book.

    A level variable per slot, no binaries. It may only sit above the real level, which never
    gains anything, so the constraint is exact. Beside a fuel source this is the rod's only cap;
    beside an electric source the day's heat of ``_add_one_thermal_flex_consumer`` caps it as well.
    """
    if not schedule_indices:
        return
    eligible = set(consumer_thermal_eligible_indices(matrix, rod, schedule_indices))
    if not rod["parent_heat_electric"]:
        covered.update(slot for slot in eligible if balance.has_demand(slot))
    level = balance.start_kwh
    for slot in range(min(schedule_indices), max(schedule_indices) + 1):
        heat = _rod_energy_expr(model, rod, [slot]) if slot in eligible else 0.0
        next_level = pulp.LpVariable(
            f"{rod['id']}_store_{slot}", lowBound=0.0, upBound=balance.capacity_kwh
        )
        model.prob += (
            next_level >= level + heat - balance.drain_kwh[slot],
            f"{rod['id']}_store_balance_{slot}",
        )
        level = next_level


def _add_hp_store_balance(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    consumer: dict,
    balance: HpStoreBalance,
    rods: list[dict],
    effective_by_day: dict[date, float],
) -> None:
    """SE: the heat pump's heat (plus its rods' heat, η = 1) stays inside the band on every slot.

    The year model's heat of a day leaves the level spread like the model's own slots, scaled to
    the energy the day must deliver (``effective_by_day``), so a day that delivers its target ends
    where it started. The level is the shared one of ``thermal_store_model`` (with the store's
    leak); ``model.hp_store_slack`` keeps its slack for the report.
    """
    if not schedule_indices:
        return
    cid = str(consumer["id"])
    first, last = min(schedule_indices), max(schedule_indices)
    book = list(range(first, last + 1))
    scaled = _hp_drain_scaled_to_days(matrix, range(first, last + 1), balance, effective_by_day)
    drain = [scaled.get(slot, 0.0) for slot in range(last + 1)]
    heat_at = _store_heat_expr(model, matrix, schedule_indices, consumer, rods, balance.efficiency)
    level = add_store_level(model, f"{cid}_hp_store", balance.store_model(drain), book, heat_at)
    if model.hp_store_slack is None:
        model.hp_store_slack = {}
    model.hp_store_slack[cid] = [level.slack[slot] for slot in book]


def _store_heat_expr(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    consumer: dict,
    rods: list[dict],
    efficiency: float,
):
    """Heat [kWh] into the store per slot: generator × efficiency plus its rods (η = 1)."""
    generator_at, rod_heat_at = _store_inflow_exprs(model, matrix, schedule_indices, consumer, rods)

    def heat_at(slot: int):
        generator = generator_at(slot)
        heat = generator * efficiency if not isinstance(generator, float) else 0.0
        rod_heat = rod_heat_at(slot)
        return heat if isinstance(rod_heat, float) else heat + rod_heat

    return heat_at


def _store_inflow_exprs(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    consumer: dict,
    rods: list[dict],
):
    """Per slot: the generator's electricity [kWh] and its rods' heat (η = 1) [kWh].

    Each is the float ``0.0`` on a slot where nothing of it may run.
    """
    from optimizer.milp_consumers import _delivery_energy_expr

    eligible = set(consumer_thermal_eligible_indices(matrix, consumer, schedule_indices))
    rod_eligible = {
        str(rod["id"]): set(consumer_thermal_eligible_indices(matrix, rod, schedule_indices))
        for rod in rods
    }

    def generator_at(slot: int):
        return _delivery_energy_expr(model, consumer, [slot]) if slot in eligible else 0.0

    def rod_heat_at(slot: int):
        heat = 0.0
        for rod in rods:
            if slot in rod_eligible[str(rod["id"])]:
                heat = heat + _rod_energy_expr(model, rod, [slot])
        return heat

    return generator_at, rod_heat_at


def _hp_drain_scaled_to_days(
    matrix: list,
    book: range,
    balance: HpStoreBalance,
    effective_by_day: dict[date, float],
) -> dict[int, float]:
    """Year-model heat per book slot, each day scaled to the heat it must deliver (0 without a target)."""
    slots_by_day: dict[date, list[int]] = {}
    for slot in book:
        slots_by_day.setdefault(matrix[slot]["date"], []).append(slot)
    drain: dict[int, float] = {}
    for day, slots in slots_by_day.items():
        model_heat = sum(balance.drain_kwh[slot] for slot in slots)
        want_heat = float(effective_by_day.get(day, 0.0)) * balance.efficiency
        factor = want_heat / model_heat if model_heat > 1e-9 else 0.0
        for slot in slots:
            drain[slot] = balance.drain_kwh[slot] * factor
        if model_heat <= 1e-9 and want_heat > 1e-9:
            # Heat to deliver but no modeled heat in the book's part of the day: spread it evenly.
            for slot in slots:
                drain[slot] = want_heat / len(slots)
    return drain


def _add_live_store_consumer(
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
    """Live + store: the heat pump (and its rods) fill the store level of the MILP (P4).

    Replaces the forced hours and the scalar floor / opportunistic budget of before: the level
    must stay in the band on every slot and end the book at the mean level of normal operation
    (design § 8.6 D2). The pulse limit per day still applies; a bottom sensor below the band
    still forces the first hour.
    """
    if not schedule_indices:
        return
    cid = str(consumer["id"])
    plan = ctx[LIVE_STORE_PLAN_KEY]
    on_vars = model.consumer_on[cid]
    eligible_set = set(consumer_thermal_eligible_indices(matrix, consumer, schedule_indices))
    _force_thermal_on_slots(
        model, cid, on_vars, [int(i) for i in ctx.get("forced_indices") or []], eligible_set
    )
    _add_live_store_pulses(model, matrix, consumer, eligible_set, running_day)
    book = list(range(min(schedule_indices), max(schedule_indices) + 1))
    store = _live_store_with_terminal(matrix, plan, book, float(model.dt_h))
    for rod in rods:
        rod_covered.setdefault(str(rod["id"]), set()).update(
            consumer_thermal_eligible_indices(matrix, rod, schedule_indices)
        )
    on_at = (lambda slot: on_vars[slot]) if store.charge_limit_kwh else None
    level = _add_live_store_level(
        model, matrix, schedule_indices, consumer, rods, store, book, on_at
    )
    if model.live_store_levels is None:
        model.live_store_levels = {}
    model.live_store_levels[cid] = (store, level)


def _live_store_with_terminal(matrix: list, plan, book: list[int], dt_h: float):
    """Store level model of the Live plan with its terminal level at the book's end."""
    from optimizer.thermal_live_store import live_store_level_model, live_store_terminal_kwh

    store = live_store_level_model(matrix, plan, dt_h)
    terminal = live_store_terminal_kwh(matrix, plan, book[-1], dt_h)
    if book[-1] < len(store.charge_limit_kwh):
        # The generator may not charge above the last slot's limit, so the plan cannot ask
        # for a higher level at the end: it could only pay slack for it.
        terminal = min(terminal, store.charge_limit_kwh[book[-1]])
    return replace(store, terminal_min_kwh=terminal)


def _add_live_store_level(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    consumer: dict,
    rods: list[dict],
    store,
    book: list[int],
    on_at,
):
    """Add the Live store level; with segments the generator's electricity goes to them."""
    cid = str(consumer["id"])
    if store.segments:
        # HeatControl P5: COP by temperature, the generator's electricity goes to segments.
        generator_at, rod_heat_at = _store_inflow_exprs(
            model, matrix, schedule_indices, consumer, rods
        )
        return add_store_level(
            model, f"{cid}_store", store, book, rod_heat_at,
            generator_kwh_at=generator_at, generator_on_at=on_at,
        )
    heat_at = _store_heat_expr(
        model, matrix, schedule_indices, consumer, rods, store.efficiency
    )
    return add_store_level(
        model, f"{cid}_store", store, book, heat_at, generator_on_at=on_at
    )


def _add_live_store_pulses(
    model: MilpHorizonModel,
    matrix: list,
    consumer: dict,
    eligible_set: set[int],
    running_day: date | None,
) -> None:
    """The heat pump's pulse limit per day still applies beside the Live store level."""
    cid = str(consumer["id"])
    on_vars = model.consumer_on[cid]
    max_pulses = _max_pulses_per_day(consumer)
    days = sorted({matrix[index]["date"] for index in eligible_set})
    for day in days:
        day_indices = [i for i in _indices_for_date(matrix, day) if i in eligible_set]
        add_max_pulses_per_day_constraints(
            model.prob,
            on_vars,
            day_indices,
            max_pulses=max_pulses,
            prefix=f"{cid}_{day.isoformat()}",
            continuing=running_day is not None and day == running_day,
        )
