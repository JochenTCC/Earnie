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
    if "hp_electric_kw" not in params:
        params["hp_electric_kw"] = float(consumer.get("nominal_power_kw", 3.0) or 3.0)
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


def _slot_aligned_thermal_energy_kwh(
    source: dict,
    matrix: list,
    *,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Modeled thermal kWh per matrix slot (same basis as profile_spec)."""
    from data.consumption_profiles import modeled_consumer_kw_at_datetime
    from optimizer.slot_duration import DEFAULT_DT_H, energy_kwh_from_kw, validate_dt_h

    validate_dt_h(DEFAULT_DT_H)
    energies: list[float] = []
    for row in matrix:
        slot_dt = row.get("slot_datetime")
        if slot_dt is None:
            energies.append(0.0)
            continue
        energies.append(
            float(
                energy_kwh_from_kw(
                    [
                        modeled_consumer_kw_at_datetime(
                            source, slot_dt, climate=climate
                        )
                        or 0.0
                    ]
                )
            )
        )
    return energies


def _daily_targets_from_slot_energy(
    matrix: list, slot_energy_kwh: list[float]
) -> dict[date, float]:
    daily: dict[date, float] = {}
    for index, row in enumerate(matrix):
        if index >= len(slot_energy_kwh):
            break
        day = row.get("date")
        if not isinstance(day, date):
            continue
        daily[day] = daily.get(day, 0.0) + float(slot_energy_kwh[index])
    return {day: round(kwh, 3) for day, kwh in daily.items() if kwh > 0.0}


def resolve_thermal_flex_contexts(
    matrix: list,
    consumers: list[dict],
    house_profile: dict | None,
    *,
    climate: ModeledClimateContext | None = None,
) -> dict[str, dict]:
    """Tagesziele je Kalendertag für thermal_annual-Flex-Verbraucher.

    Slot-aligned to the horizon matrix (same energy basis as
    ``planning_thermal_daily_targets`` / profile_spec), not full-calendar HDD.
    Constraint builder sums only schedule-eligible slots so sunrise book
    windows match book ``spec_flex_targets_kwh``.
    """
    if not house_profile or not matrix:
        return {}
    from house_config.planning_flex_bridge import _house_thermal_consumers
    from optimizer.absent_mode import (
        matrix_is_live_snapshot,
        resolve_absent_status,
        thermal_source_with_live_absent,
    )

    thermal_by_id = {
        str(item["id"]): item
        for item in _house_thermal_consumers(house_profile)
    }
    live_absent = False
    is_live = matrix_is_live_snapshot(matrix)
    if is_live:
        live_absent = bool(resolve_absent_status(house_profile)["effective"])
    contexts: dict[str, dict] = {}
    for consumer in consumers:
        if not is_thermal_flex_consumer(consumer):
            continue
        cid = str(consumer["id"])
        source = thermal_by_id.get(cid)
        if not source:
            continue
        source = thermal_source_with_live_absent(
            source, live_absent_active=live_absent
        )
        slot_energy = _slot_aligned_thermal_energy_kwh(
            source, matrix, climate=climate
        )
        ctx: dict = {
            "daily_targets": _daily_targets_from_slot_energy(matrix, slot_energy),
            "slot_energy_kwh": slot_energy,
            "targets_slot_aligned": True,
        }
        if is_live:
            live_ctx = _live_store_flex_overlay(
                matrix, source, house_profile, consumer
            )
            if live_ctx:
                ctx.update(live_ctx)
        contexts[cid] = ctx
    return contexts


def _live_store_flex_overlay(
    matrix: list,
    source: dict,
    house_profile: dict,
    milp_consumer: dict,
) -> dict | None:
    """Open-loop store floor + opportunistic scalars for Live snapshots only."""
    from data.outdoor_forecast import get_outdoor_forecast_with_fallback
    from optimizer.thermal_coupled import heat_storage_enabled
    from optimizer.thermal_live_store import (
        live_min_kwh_by_day,
        map_forced_hours_to_slot_indices,
        plan_live_store_for_thermal_consumer,
    )
    from optimizer.thermal_targets import thermal_horizon_hours_from_slots

    thermal = source.get("thermal") or source
    if not heat_storage_enabled(thermal.get("heat_storage")):
        return None
    horizon_h = thermal_horizon_hours_from_slots(len(matrix))
    fallback_ambient = 10.0
    try:
        from integrations.loxone_client import _read_optional_temp_c
        from settings.ehal_marker_resolve import marker_sens_temperature_outside

        ambient_io = marker_sens_temperature_outside(house_doc=None)
        live_amb = _read_optional_temp_c(ambient_io)
        if live_amb is not None:
            fallback_ambient = float(live_amb)
    except Exception:
        pass
    ambient_forecast, _src = get_outdoor_forecast_with_fallback(
        horizon=horizon_h,
        fallback_ambient_c=fallback_ambient,
    )
    plan = plan_live_store_for_thermal_consumer(
        source,
        house_profile=house_profile,
        ambient_forecast_c=ambient_forecast,
        house_doc=None,
    )
    if plan is None:
        return None
    eligible = consumer_thermal_eligible_indices(
        matrix, milp_consumer, list(range(len(matrix)))
    )
    forced = map_forced_hours_to_slot_indices(
        matrix, plan.forced_hour_flags, eligible_indices=eligible
    )
    return {
        "forced_indices": forced,
        "floor_kwh": plan.floor_electric_kwh,
        "opp_cap_kwh": plan.opp_cap_electric_kwh,
        "live_day_min_kwh": live_min_kwh_by_day(matrix, plan),
        "live_store_start_c": plan.start_temp_c,
        "live_store_temp_low_c": plan.temp_low_c,
    }


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
    # Need ≥1 OFF between pulses; max ON in N slots with run-length ≤ H.
    gaps_needed = max(0, (day_slots - 1) // (max_hours + 1))
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
    for consumer in model.planned_consumers:
        if not is_thermal_flex_consumer(consumer):
            continue
        _add_one_thermal_flex_consumer(
            model,
            matrix,
            schedule_indices,
            consumer,
            thermal_contexts.get(consumer["id"]) or {},
            continuing=bool(continue_on.get(consumer["id"], False)),
        )


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


def _add_one_thermal_flex_consumer(
    model: MilpHorizonModel,
    matrix: list,
    schedule_indices: list[int],
    consumer: dict,
    ctx: dict,
    *,
    continuing: bool,
) -> None:
    from optimizer.consumer_power import power_limits_kw
    from optimizer.milp_consumers import _delivery_energy_expr, _max_deliverable_kwh

    cid = consumer["id"]
    daily_targets: dict[date, float] = dict(ctx.get("daily_targets") or {})
    live_day_min: dict[date, float] = dict(ctx.get("live_day_min_kwh") or {})
    forced_indices = [int(i) for i in (ctx.get("forced_indices") or [])]
    if not daily_targets and not live_day_min and not forced_indices:
        return
    on_vars = model.consumer_on[cid]
    max_hours = _max_on_hours(consumer)
    max_pulses = _max_pulses_per_day(consumer)
    if not forced_indices:
        add_max_on_duration_constraints(
            model.prob, on_vars, max_hours=max_hours, prefix=cid
        )
    # Sunrise: schedule_indices are book (SA1→SA2). Spec/plausibility WP is
    # book-window energy — require delivery only on those slots, using the
    # exact slot-aligned kWh (not calendar HDD × day_slots/96).
    eligible_set = set(
        consumer_thermal_eligible_indices(matrix, consumer, schedule_indices)
    )
    _force_thermal_on_slots(model, cid, on_vars, forced_indices, eligible_set)
    slot_energy = list(ctx.get("slot_energy_kwh") or [])
    slot_aligned = bool(ctx.get("targets_slot_aligned")) and bool(slot_energy)
    for day in sorted(set(daily_targets) | set(live_day_min)):
        matrix_day_indices = _indices_for_date(matrix, day)
        day_indices = [
            index for index in matrix_day_indices if index in eligible_set
        ]
        if not day_indices:
            continue
        _, max_kw = power_limits_kw(consumer)
        max_deliverable = _max_deliverable_kwh(
            consumer, day_indices, dt_h=model.dt_h
        )
        if slot_aligned:
            prorated = round(
                sum(
                    float(slot_energy[index])
                    for index in day_indices
                    if index < len(slot_energy)
                ),
                3,
            )
        else:
            prorated = _prorate_thermal_day_target_kwh(
                float(daily_targets.get(day, 0.0) or 0.0), len(day_indices)
            )
        live_min = float(live_day_min.get(day, 0.0) or 0.0)
        # Live store overlay: HDD ignored; floor via forced_indices; live_min = opp only.
        live_overlay = ctx.get("live_store_start_c") is not None
        want = live_min if live_overlay else max(prorated, live_min)
        if forced_indices:
            op_max_kwh = max_deliverable
        else:
            op_slots = _max_on_slots_with_limits(
                len(day_indices), max_hours=max_hours, max_pulses=max_pulses
            )
            op_max_kwh = op_slots * float(max_kw) * float(model.dt_h)
        effective = min(want, max_deliverable, op_max_kwh)
        if effective <= 1e-9:
            continue
        if not forced_indices:
            add_max_pulses_per_day_constraints(
                model.prob,
                on_vars,
                day_indices,
                max_pulses=max_pulses,
                prefix=f"{cid}_{day.isoformat()}",
                continuing=continuing,
            )
        model.prob += (
            _delivery_energy_expr(model, consumer, day_indices) >= effective,
            f"{cid}_thermal_day_{day.isoformat()}",
        )
