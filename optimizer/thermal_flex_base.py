"""Thermal flex basics: predicates, eligible slots, pulse limits.

Split from ``thermal_flex_context`` (import facade).
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pulp

from house_config.generic_schedule import generic_allowed_slot_hours
from optimizer.charging_context import matrix_slot_datetime

if TYPE_CHECKING:
    from optimizer.milp_horizon import MilpHorizonModel

THERMAL_MAX_ON_HOURS = 4
THERMAL_MAX_PULSES_PER_DAY = 4
# Context key of the Live store plan (``LiveStorePlan``) of a heat pump with a store.
LIVE_STORE_PLAN_KEY = "live_store_plan"


def is_thermal_flex_consumer(consumer: dict) -> bool:
    return consumer.get("daily_target_source") == "thermal_annual"


def is_heating_rod_consumer(consumer: dict) -> bool:
    return consumer.get("daily_target_source") == "heating_rod"


def thermal_flex_window(consumer: dict) -> dict | None:
    window = consumer.get("thermal_flex_window")
    return window if isinstance(window, dict) and window else None


def consumer_thermal_eligible_indices(
    matrix: list,
    consumer: dict,
    schedule_indices: list[int],
) -> list[int]:
    """Erlaubte MILP-Slots für thermische Flex (optional Tagesfenster)."""
    window = thermal_flex_window(consumer)
    if not window:
        return list(schedule_indices)
    allowed_hours = generic_allowed_slot_hours(
        int(window.get("start_hour", 0)) % 24,
        float(window.get("start_shift_h", 0.0) or 0.0),
        float(window.get("duration_h", 24.0) or 24.0),
    )
    eligible: list[int] = []
    for index in schedule_indices:
        if index < 0 or index >= len(matrix):
            continue
        slot_dt = matrix_slot_datetime(matrix, index)
        if slot_dt.hour in allowed_hours:
            eligible.append(index)
    return eligible


def _indices_for_date(matrix: list, day: date) -> list[int]:
    return [
        index
        for index, row in enumerate(matrix)
        if row.get("date") == day
    ]


def _max_on_hours(consumer: dict) -> int:
    """Max consecutive ON slots (config ``max_on_quarterhours`` = real MILP slots)."""
    raw = consumer.get("max_on_quarterhours")
    if raw is not None:
        return max(1, int(raw))
    return THERMAL_MAX_ON_HOURS * 4  # legacy default was hours; keep ~same wall-clock


def _max_pulses_per_day(consumer: dict) -> int:
    raw = consumer.get("max_pulses_per_day")
    if raw is not None:
        return max(1, int(raw))
    return THERMAL_MAX_PULSES_PER_DAY


def _prorate_thermal_day_target_kwh(
    full_day_kwh: float,
    day_slots: int,
    *,
    dt_h: float | None = None,
) -> float:
    """Scale full-calendar HDD kWh to the fraction of the day present in the horizon."""
    from .slot_duration import DEFAULT_DT_H, slots_for_wall_hours, validate_dt_h

    if day_slots <= 0 or full_day_kwh <= 0.0:
        return 0.0
    dt = validate_dt_h(DEFAULT_DT_H if dt_h is None else dt_h)
    slots_per_day = slots_for_wall_hours(24.0, dt)
    if day_slots >= slots_per_day:
        return float(full_day_kwh)
    return round(float(full_day_kwh) * (day_slots * dt / 24.0), 3)


def _max_on_slots_with_limits(
    day_slots: int,
    *,
    max_hours: int,
    max_pulses: int,
) -> int:
    """Upper bound on ON hours under consecutive-ON and pulse caps."""
    if day_slots <= 0 or max_hours < 1 or max_pulses < 1:
        return 0
    by_pulses = max_hours * max_pulses
    if day_slots <= max_hours:
        return min(day_slots, by_pulses)
    # Need ≥1 OFF between pulses; max ON in N slots with run-length ≤ H is
    # N - N // (H + 1) (every window of H + 1 slots needs one OFF).
    gaps_needed = day_slots // (max_hours + 1)
    by_consecutive = day_slots - gaps_needed
    return min(day_slots, by_pulses, by_consecutive)


def add_max_on_duration_constraints(
    prob: pulp.LpProblem,
    on_vars: list,
    *,
    max_hours: int,
    prefix: str,
) -> None:
    """Verbietet mehr als max_hours aufeinanderfolgende EIN-Slots."""
    if max_hours < 1 or not on_vars:
        return
    horizon = len(on_vars)
    for start in range(horizon - max_hours):
        prob += (
            pulp.lpSum(on_vars[start : start + max_hours + 1]) <= max_hours,
            f"{prefix}_max_on_{start}",
        )


def add_max_pulses_per_day_constraints(
    prob: pulp.LpProblem,
    on_vars: list,
    day_indices: list[int],
    *,
    max_pulses: int,
    prefix: str,
    continuing: bool = False,
) -> None:
    """Begrenzt Block-Starts pro Kalendertag."""
    if max_pulses <= 0 or not day_indices:
        return
    sorted_idx = sorted(day_indices)
    starts: list = []
    for position, slot in enumerate(sorted_idx):
        if position == 0:
            prev_on: pulp.LpAffineExpression | int = 1 if continuing else 0
        else:
            prev_slot = sorted_idx[position - 1]
            prev_on = on_vars[prev_slot] if prev_slot == slot - 1 else 0
        start_var = pulp.LpVariable(f"{prefix}_start_{slot}", cat=pulp.LpBinary)
        prob += start_var >= on_vars[slot] - prev_on
        prob += start_var <= on_vars[slot]
        starts.append(start_var)
    if starts:
        prob += pulp.lpSum(starts) <= max_pulses



def _rod_energy_expr(model: MilpHorizonModel, rod: dict, indices: list[int]):
    from optimizer.milp_consumers import _delivery_energy_expr

    return _delivery_energy_expr(model, rod, indices)


def _force_thermal_on_slots(
    model: MilpHorizonModel,
    cid: str,
    on_vars: list,
    forced_indices: list[int],
    eligible_set: set[int],
) -> None:
    for index in forced_indices:
        if index not in eligible_set or index < 0 or index >= len(on_vars):
            continue
        model.prob += (on_vars[index] >= 1, f"{cid}_thermal_forced_{index}")
