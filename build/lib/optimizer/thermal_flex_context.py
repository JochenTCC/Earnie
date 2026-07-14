"""MILP-Zeitfenster und Tagesziele für Haus-Wärme (thermal_annual / Thermals P1a)."""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import pulp

from house_config.generic_schedule import generic_allowed_slot_hours
from optimizer.charging_context import matrix_slot_datetime

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext
    from optimizer.milp_horizon import MilpHorizonModel

THERMAL_MAX_ON_HOURS = 4
THERMAL_MAX_PULSES_PER_DAY = 4


def is_thermal_flex_consumer(consumer: dict) -> bool:
    return consumer.get("daily_target_source") == "thermal_annual"


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


def thermal_daily_kwh_for_date(
    consumer: dict,
    profile: dict,
    day: date,
    *,
    climate: ModeledClimateContext | None = None,
) -> float:
    """Tages-WP-Strom (kWh) aus HDD/Klima für einen thermal_annual-Verbraucher."""
    from data.heating_need import daily_electric_kwh, heating_params_from_thermal

    thermal = consumer.get("thermal") or consumer
    params = heating_params_from_thermal(thermal)
    params["latitude"] = float(profile["latitude"])
    params["longitude"] = float(profile["longitude"])
    day_index = day.timetuple().tm_yday - 1
    if climate is not None:
        bundle = climate._bundle_for_calendar_year(day.year)
        area_m2 = float(params.get("solar_thermal_area_m2", 0.0) or 0.0)
        hourly_wm2 = None
        if area_m2 > 0.0:
            from data.modeled_climate import collector_surface_from_thermal

            surface = collector_surface_from_thermal(thermal, profile)
            hourly_wm2 = bundle.collector_surface_series(surface)
        daily = daily_electric_kwh(
            **params,
            hourly_temperature_c=bundle.temperature_c,
            hourly_collector_wm2=hourly_wm2,
        )
        if 0 <= day_index < len(daily):
            return float(daily[day_index])
        return 0.0
    daily = daily_electric_kwh(**params)
    if 0 <= day_index < len(daily):
        return float(daily[day_index])
    return 0.0


def resolve_thermal_flex_contexts(
    matrix: list,
    consumers: list[dict],
    house_profile: dict | None,
    *,
    climate: ModeledClimateContext | None = None,
) -> dict[str, dict]:
    """Tagesziele je Kalendertag für thermal_annual-Flex-Verbraucher."""
    if not house_profile or not matrix:
        return {}
    from house_config.planning_flex_bridge import _house_thermal_consumers

    thermal_by_id = {
        str(item["id"]): item
        for item in _house_thermal_consumers(house_profile)
    }
    dates = sorted(
        {
            row.get("date")
            for row in matrix
            if row.get("date") is not None
        }
    )
    contexts: dict[str, dict] = {}
    for consumer in consumers:
        if not is_thermal_flex_consumer(consumer):
            continue
        cid = str(consumer["id"])
        source = thermal_by_id.get(cid)
        if not source:
            continue
        daily_targets: dict[date, float] = {}
        for day in dates:
            if not isinstance(day, date):
                continue
            kwh = thermal_daily_kwh_for_date(
                source,
                house_profile,
                day,
                climate=climate,
            )
            if kwh > 0.0:
                daily_targets[day] = round(kwh, 3)
        contexts[cid] = {"daily_targets": daily_targets}
    return contexts


def _indices_for_date(matrix: list, day: date) -> list[int]:
    return [
        index
        for index, row in enumerate(matrix)
        if row.get("date") == day
    ]


def _max_on_hours(consumer: dict) -> int:
    raw = consumer.get("max_on_quarterhours")
    if raw is not None:
        return max(1, int(raw) // 4)
    return THERMAL_MAX_ON_HOURS


def _max_pulses_per_day(consumer: dict) -> int:
    raw = consumer.get("max_pulses_per_day")
    if raw is not None:
        return max(1, int(raw))
    return THERMAL_MAX_PULSES_PER_DAY


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


def add_thermal_flex_constraints(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    thermal_contexts: dict[str, dict],
    *,
    consumer_continue_on: dict[str, bool] | None = None,
) -> None:
    """Tages-Lieferung, max. Pulsdauer und max. Pulse/Tag für thermal_annual."""
    from optimizer.milp_consumers import _delivery_energy_expr, _max_deliverable_kwh
    from optimizer.consumer_power import power_limits_kw

    continue_on = consumer_continue_on or {}
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        if not is_thermal_flex_consumer(consumer):
            continue
        ctx = thermal_contexts.get(cid) or {}
        daily_targets: dict[date, float] = ctx.get("daily_targets") or {}
        if not daily_targets:
            continue
        on_vars = model.consumer_on[cid]
        max_hours = _max_on_hours(consumer)
        max_pulses = _max_pulses_per_day(consumer)
        add_max_on_duration_constraints(
            model.prob,
            on_vars,
            max_hours=max_hours,
            prefix=cid,
        )
        eligible_all = consumer_thermal_eligible_indices(
            matrix,
            consumer,
            schedule_indices,
        )
        eligible_set = set(eligible_all)
        for day, target_kwh in daily_targets.items():
            day_indices = [
                index
                for index in _indices_for_date(matrix, day)
                if index in eligible_set
            ]
            if not day_indices or target_kwh <= 0.0:
                continue
            _, max_kw = power_limits_kw(consumer)
            max_deliverable = _max_deliverable_kwh(consumer, day_indices)
            effective = min(float(target_kwh), max_deliverable)
            add_max_pulses_per_day_constraints(
                model.prob,
                on_vars,
                day_indices,
                max_pulses=max_pulses,
                prefix=f"{cid}_{day.isoformat()}",
                continuing=bool(continue_on.get(cid, False)),
            )
            model.prob += (
                _delivery_energy_expr(model, consumer, day_indices) >= effective,
                f"{cid}_thermal_day_{day.isoformat()}",
            )
