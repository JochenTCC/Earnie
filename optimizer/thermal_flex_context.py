"""MILP-Zeitfenster und Tagesziele für Haus-Wärme (thermal_annual / Thermals P1a)."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime
from typing import TYPE_CHECKING

import pulp

from house_config.generic_schedule import generic_allowed_slot_hours
from optimizer.charging_context import matrix_slot_datetime
from optimizer.hp_store import HP_STORE_CONTEXT_KEY, HpStoreBalance, hp_store_balance
from optimizer.rod_store import STORE_BALANCE_CONTEXT_KEY, RodStoreBalance, rod_store_balance
from optimizer.thermal_store_model import add_store_level

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext
    from optimizer.milp_horizon import MilpHorizonModel

logger = logging.getLogger(__name__)

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


def thermal_daily_kwh_for_date(
    consumer: dict,
    profile: dict,
    day: date,
    *,
    climate: ModeledClimateContext | None = None,
) -> float:
    """Tages-WP-Strom (kWh) aus HDD/Klima für einen thermal_annual-Verbraucher."""
    from data.heating_need import daily_electric_kwh

    return _thermal_daily_for_date(
        consumer, profile, day, climate=climate, daily_fn=daily_electric_kwh
    )


def thermal_daily_heat_kwh_for_date(
    consumer: dict,
    profile: dict,
    day: date,
    *,
    climate: ModeledClimateContext | None = None,
) -> float:
    """Delivered heat (kWh) of the day = input energy (power or fuel) × efficiency."""
    from data.heating_need import daily_electric_kwh, daily_fuel_kwh
    from house_config.heat_source import (
        consumer_heat_source,
        heat_source_efficiency,
        heat_source_is_electric,
    )

    heat_source = consumer_heat_source(consumer)
    daily_fn = daily_electric_kwh if heat_source_is_electric(heat_source) else daily_fuel_kwh
    input_kwh = _thermal_daily_for_date(
        consumer, profile, day, climate=climate, daily_fn=daily_fn
    )
    return input_kwh * heat_source_efficiency(heat_source)


def thermal_daily_fuel_kwh_for_date(
    consumer: dict,
    profile: dict,
    day: date,
    *,
    climate: ModeledClimateContext | None = None,
) -> float:
    """Fuel (final energy, kWh) of the day; 0 for an electric heat source."""
    from data.heating_need import daily_fuel_kwh

    return _thermal_daily_for_date(
        consumer, profile, day, climate=climate, daily_fn=daily_fuel_kwh
    )


def _thermal_daily_for_date(
    consumer: dict,
    profile: dict,
    day: date,
    *,
    climate: ModeledClimateContext | None,
    daily_fn,
) -> float:
    from data.heating_need import heating_params_from_thermal
    from house_config.heating_systems import consumer_input_power_kw

    thermal = consumer.get("thermal") or consumer
    params = heating_params_from_thermal(thermal)
    params["latitude"] = float(profile["latitude"])
    params["longitude"] = float(profile["longitude"])
    if "hp_electric_kw" not in params:
        params["hp_electric_kw"] = consumer_input_power_kw(consumer)
    day_index = day.timetuple().tm_yday - 1
    if climate is not None:
        from data.modeled_climate import collector_surface_from_thermal
        from optimizer.house_gains import thermal_climate_kwargs

        bundle = climate._bundle_for_calendar_year(day.year)
        daily = daily_fn(
            **params,
            **thermal_climate_kwargs(
                bundle, thermal, collector_surface_from_thermal(thermal, profile)
            ),
        )
        if 0 <= day_index < len(daily):
            return float(daily[day_index])
        return 0.0
    daily = daily_fn(**params)
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
    from data.consumption_profiles import modeled_consumer_kw_for_slots
    from optimizer.slot_duration import DEFAULT_DT_H, energy_kwh_from_kw, validate_dt_h

    validate_dt_h(DEFAULT_DT_H)
    slot_dts = [row.get("slot_datetime") for row in matrix]
    kw_values = iter(
        modeled_consumer_kw_for_slots(
            source,
            [slot_dt for slot_dt in slot_dts if slot_dt is not None],
            climate=climate,
        )
    )
    energies: list[float] = []
    for slot_dt in slot_dts:
        if slot_dt is None:
            energies.append(0.0)
            continue
        energies.append(float(energy_kwh_from_kw([next(kw_values) or 0.0])))
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
    rod_store_start_kwh: dict[str, float] | None = None,
    hp_store_start_kwh: dict[str, float] | None = None,
) -> dict[str, dict]:
    """Tagesziele je Kalendertag für thermal_annual-Flex-Verbraucher.

    Slot-aligned to the horizon matrix (same energy basis as
    ``planning_thermal_daily_targets`` / profile_spec), not full-calendar HDD.
    Constraint builder sums only schedule-eligible slots so sunrise book
    windows match book ``spec_flex_targets_kwh``. ``rod_store_start_kwh``: the SE's
    carried store level per heating rod (``optimizer.rod_store``), ``hp_store_start_kwh`` the same
    per heat pump (``optimizer.hp_store``).
    """
    if not house_profile or not matrix:
        return {}
    from house_config.planning_flex_bridge import _house_thermal_consumers
    from optimizer.absent_mode import (
        resolve_absent_status,
        thermal_source_with_live_absent,
    )
    from optimizer.live_cycle_scope import is_live_thermal_planning

    thermal_by_id = {
        str(item["id"]): item
        for item in _house_thermal_consumers(house_profile)
    }
    live_absent = False
    is_live = is_live_thermal_planning(matrix)
    if is_live:
        live_absent = bool(resolve_absent_status(house_profile)["effective"])
    contexts: dict[str, dict] = {}
    for consumer in consumers:
        if is_heating_rod_consumer(consumer):
            parent = thermal_by_id.get(str(consumer["parent_id"]))
            if parent is None:
                continue
            if is_live:
                contexts[str(consumer["id"])] = _live_rod_context(
                    matrix, consumer, parent, house_profile
                )
            else:
                contexts[str(consumer["id"])] = {
                    STORE_BALANCE_CONTEXT_KEY: rod_store_balance(
                        matrix,
                        str(consumer["id"]),
                        parent,
                        house_profile,
                        start_levels_kwh=rod_store_start_kwh,
                        climate=climate,
                    )
                }
            continue
        if not is_thermal_flex_consumer(consumer):
            continue
        cid = str(consumer["id"])
        source = thermal_by_id.get(cid)
        if not source:
            continue
        source = thermal_source_with_live_absent(
            source, live_absent_active=live_absent
        )
        live_ctx = (
            _live_store_flex_overlay(matrix, source, house_profile, consumer)
            if is_live
            else None
        )
        if live_ctx is not None:
            # Live + heat storage: horizon plan only, no year profile (ThermalHorizon P2).
            contexts[cid] = live_ctx
            continue
        if is_live:
            # Live without storage: house-only horizon plan (ThermalHorizon P4).
            slot_energy = _live_house_slot_energy_kwh(matrix, source, house_profile)
        else:
            slot_energy = _slot_aligned_thermal_energy_kwh(
                source, matrix, climate=climate
            )
        contexts[cid] = {
            "daily_targets": _daily_targets_from_slot_energy(matrix, slot_energy),
            "slot_energy_kwh": slot_energy,
            "targets_slot_aligned": True,
        }
        if not is_live and _heat_source_is_electric(source):
            contexts[cid][HP_STORE_CONTEXT_KEY] = hp_store_balance(
                cid,
                source,
                slot_energy,
                _heat_source_efficiency(source),
                start_levels_kwh=hp_store_start_kwh,
            )
    return contexts


def _heat_source_is_electric(source: dict) -> bool:
    from house_config.heat_source import consumer_heat_source, heat_source_is_electric

    return heat_source_is_electric(consumer_heat_source(source))


def _heat_source_efficiency(source: dict) -> float:
    from house_config.heat_source import consumer_heat_source, heat_source_efficiency

    return heat_source_efficiency(consumer_heat_source(source))


def live_rod_ready(rod: dict, parent: dict) -> bool:
    """All Live signals of the rod are bound; logs the missing ones once per cycle."""
    from house_config.heating_rod_bindings import missing_live_signals
    from optimizer.live_cycle_scope import cycle_memo

    missing = missing_live_signals(rod, parent)
    if missing:

        def _log_missing() -> bool:
            logger.info(
                "Heizstab '%s' wird in Live nicht geplant, es fehlt: %s.",
                rod["id"],
                ", ".join(missing),
            )
            return True

        cycle_memo(("rod_signals_missing", str(rod["id"])), _log_missing)
    return not missing


def live_rod_heat_cap_kwh(parent: dict, house_profile: dict, matrix: list) -> float:
    """Heat [kWh] the rod may add in Live.

    Beside an electric source the store level of the MILP caps the rod (HeatControl P4); this
    is only the store's room over the horizon, so the rod gets planned at all. Beside a fuel
    source it is the cap itself, for the first calendar day of the matrix: the room up to the
    charge maximum plus the store's draw (and loss) until midnight. The rod's heat displaces
    the boiler's, so that draw is no floor to subtract but heat the rod may deliver. Same plan
    and same absent-mode setback as the heat source itself.
    """
    from house_config.heat_source import consumer_heat_source, heat_source_is_electric
    from optimizer.absent_mode import resolve_absent_status, thermal_source_with_live_absent
    from optimizer.thermal_live_store import live_store_plan_for_matrix

    source = thermal_source_with_live_absent(
        parent,
        live_absent_active=bool(resolve_absent_status(house_profile)["effective"]),
    )
    plan = live_store_plan_for_matrix(source, house_profile, matrix)
    if plan is None:
        raise ValueError(
            f"Heizstab an '{parent.get('id')}': Live-Speicherplan fehlt, der Heizstab setzt "
            "einen Wärmespeicher voraus (heat_storage im Heizsystem)."
        )
    if heat_source_is_electric(consumer_heat_source(parent)):
        return round(float(plan.charge_room_heat_kwh), 3)
    return round(float(plan.charge_room_heat_kwh_within(_hours_to_first_midnight(matrix))), 3)


def _hours_to_first_midnight(matrix: list) -> float:
    """Hours from the matrix start to the end of its first calendar day."""
    from datetime import datetime, time, timedelta

    start = matrix_slot_datetime(matrix, 0)
    midnight = datetime.combine(start.date() + timedelta(days=1), time(0, 0), tzinfo=start.tzinfo)
    return (midnight - start).total_seconds() / 3600.0


def _live_rod_context(matrix: list, rod: dict, parent: dict, house_profile: dict) -> dict:
    """Live: pulse limit for a real switch; a fuel parent caps the rod here (no flex entry).

    Beside an electric parent the store overlay of the parent already caps the rod
    (``_add_live_store_consumer``). Only the first day.
    """
    if not live_rod_ready(rod, parent):
        return {}
    ctx: dict = {"live_pulse_limit": True}
    if not rod["parent_heat_electric"]:
        first_day = matrix_slot_datetime(matrix, 0).date()
        ctx["daily_heat_cap_kwh"] = {
            first_day: live_rod_heat_cap_kwh(parent, house_profile, matrix)
        }
    return ctx


def _live_house_slot_energy_kwh(
    matrix: list,
    source: dict,
    house_profile: dict,
) -> list[float]:
    from optimizer.thermal_live_store import (
        hourly_electric_to_slot_energy_kwh,
        live_house_plan_for_matrix,
    )

    plan = live_house_plan_for_matrix(source, house_profile, matrix)
    if plan is None:
        raise ValueError(
            f"Live-Hausplan für '{source.get('id')}' fehlt (Wärmespeicher aktiv?)."
        )
    return hourly_electric_to_slot_energy_kwh(matrix, plan.electric_by_hour)


def _live_store_flex_overlay(
    matrix: list,
    source: dict,
    house_profile: dict,
    milp_consumer: dict,
) -> dict | None:
    """Live + heat storage: the store level of the MILP (HeatControl P4, design § 8.6).

    The plan carries readings, band and the normal-operation forecast; the constraint builder
    turns it into the level (``_add_live_store_consumer``). Only a bottom sensor below the band
    still forces the first hour, as before.
    """
    from optimizer.thermal_live_store import (
        live_store_plan_for_matrix,
        map_forced_hours_to_slot_indices,
    )

    plan = live_store_plan_for_matrix(source, house_profile, matrix)
    if plan is None:
        return None
    forced: list[int] = []
    if plan.temp_low_c is not None and float(plan.temp_low_c) < float(plan.band.min_c) - 1e-9:
        eligible = consumer_thermal_eligible_indices(
            matrix, milp_consumer, list(range(len(matrix)))
        )
        forced = map_forced_hours_to_slot_indices(matrix, [True], eligible_indices=eligible)
    return {
        "forced_indices": forced,
        "live_store_start_c": plan.start_temp_c,
        "live_store_temp_low_c": plan.temp_low_c,
        # The store level and the charge target (HeatControl P3/P4) come from this plan.
        LIVE_STORE_PLAN_KEY: plan,
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
    rods = [c for c in model.planned_consumers if is_heating_rod_consumer(c)]
    covered: dict[str, set[int]] = {str(rod["id"]): set() for rod in rods}
    for consumer in model.planned_consumers:
        if not is_thermal_flex_consumer(consumer):
            continue
        parent_rods = [rod for rod in rods if rod["parent_id"] == consumer["id"]]
        ctx = thermal_contexts.get(consumer["id"]) or {}
        if ctx.get(LIVE_STORE_PLAN_KEY) is not None:
            _add_live_store_consumer(
                model,
                matrix,
                schedule_indices,
                consumer,
                ctx,
                continuing=bool(continue_on.get(consumer["id"], False)),
                rods=parent_rods,
                rod_covered=covered,
            )
            continue
        effective_by_day = _add_one_thermal_flex_consumer(
            model,
            matrix,
            schedule_indices,
            consumer,
            ctx,
            continuing=bool(continue_on.get(consumer["id"], False)),
            rods=parent_rods,
            rod_covered=covered,
        )
        hp_balance = ctx.get(HP_STORE_CONTEXT_KEY)
        if hp_balance is not None:
            _add_hp_store_balance(
                model, matrix, schedule_indices, consumer, hp_balance, parent_rods, effective_by_day
            )
    for rod in rods:
        if not rod["parent_heat_electric"]:
            _add_fuel_parent_rod_caps(
                model,
                matrix,
                schedule_indices,
                rod,
                thermal_contexts.get(rod["id"]) or {},
                covered[str(rod["id"])],
            )
        balance = (thermal_contexts.get(rod["id"]) or {}).get(STORE_BALANCE_CONTEXT_KEY)
        if balance is not None:
            _add_rod_store_balance(
                model, matrix, schedule_indices, rod, balance, covered[str(rod["id"])]
            )
        _force_rod_off_outside(model, rod, covered[str(rod["id"])])
        if (thermal_contexts.get(rod["id"]) or {}).get("live_pulse_limit"):
            _add_live_rod_pulse_limit(
                model,
                matrix,
                rod,
                covered[str(rod["id"])],
                continuing=bool(continue_on.get(rod["id"], False)),
            )


def _rod_energy_expr(model: MilpHorizonModel, rod: dict, indices: list[int]):
    from optimizer.milp_consumers import _delivery_energy_expr

    return _delivery_energy_expr(model, rod, indices)


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
    continuing: bool,
    rods: list[dict],
    rod_covered: dict[str, set[int]],
) -> None:
    """Live + store: the heat pump (and its rods) fill the store level of the MILP (P4).

    Replaces the forced hours and the scalar floor / opportunistic budget of before: the level
    must stay in the band on every slot and end the book at the mean level of normal operation
    (design § 8.6 D2). The pulse limit per day still applies; a bottom sensor below the band
    still forces the first hour.
    """
    from optimizer.thermal_live_store import live_store_level_model, live_store_terminal_kwh

    if not schedule_indices:
        return
    cid = str(consumer["id"])
    plan = ctx[LIVE_STORE_PLAN_KEY]
    on_vars = model.consumer_on[cid]
    eligible_set = set(consumer_thermal_eligible_indices(matrix, consumer, schedule_indices))
    _force_thermal_on_slots(
        model, cid, on_vars, [int(i) for i in ctx.get("forced_indices") or []], eligible_set
    )
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
            continuing=continuing,
        )
    book = list(range(min(schedule_indices), max(schedule_indices) + 1))
    store = live_store_level_model(matrix, plan, float(model.dt_h))
    terminal = live_store_terminal_kwh(matrix, plan, book[-1], float(model.dt_h))
    if book[-1] < len(store.charge_limit_kwh):
        # The generator may not charge above the last slot's limit, so the plan cannot ask
        # for a higher level at the end: it could only pay slack for it.
        terminal = min(terminal, store.charge_limit_kwh[book[-1]])
    store = replace(store, terminal_min_kwh=terminal)
    for rod in rods:
        rod_covered.setdefault(str(rod["id"]), set()).update(
            consumer_thermal_eligible_indices(matrix, rod, schedule_indices)
        )
    on_at = (lambda slot: on_vars[slot]) if store.charge_limit_kwh else None
    if store.segments:
        # HeatControl P5: COP by temperature, the generator's electricity goes to segments.
        generator_at, rod_heat_at = _store_inflow_exprs(
            model, matrix, schedule_indices, consumer, rods
        )
        level = add_store_level(
            model, f"{cid}_store", store, book, rod_heat_at,
            generator_kwh_at=generator_at, generator_on_at=on_at,
        )
    else:
        heat_at = _store_heat_expr(
            model, matrix, schedule_indices, consumer, rods, store.efficiency
        )
        level = add_store_level(
            model, f"{cid}_store", store, book, heat_at, generator_on_at=on_at
        )
    if model.live_store_levels is None:
        model.live_store_levels = {}
    model.live_store_levels[cid] = (store, level)


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
    continuing: bool,
) -> None:
    """A real rod hangs on a relay: no 15-minute flicker (SE keeps its goldens unchanged)."""
    for day in sorted({matrix[index].get("date") for index in covered}):
        add_max_pulses_per_day_constraints(
            model.prob,
            model.consumer_on[rod["id"]],
            [index for index in _indices_for_date(matrix, day) if index in covered],
            max_pulses=_max_pulses_per_day(rod),
            prefix=f"{rod['id']}_{day.isoformat()}",
            continuing=continuing,
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
    continuing: bool,
    rods: list[dict] | None = None,
    rod_covered: dict[str, set[int]] | None = None,
) -> dict[date, float]:
    """Constraints of one thermal_annual consumer; returns the energy [kWh] it must deliver per day."""
    from optimizer.consumer_power import power_limits_kw
    from optimizer.milp_consumers import _delivery_energy_expr, _max_deliverable_kwh

    rods = rods or []
    rod_covered = rod_covered if rod_covered is not None else {}

    cid = consumer["id"]
    daily_targets: dict[date, float] = dict(ctx.get("daily_targets") or {})
    forced_indices = [int(i) for i in (ctx.get("forced_indices") or [])]
    effective_by_day: dict[date, float] = {}
    if not daily_targets and not forced_indices:
        return effective_by_day
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
    for day in sorted(daily_targets):
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
        want = _thermal_day_want_kwh(ctx, day, day_indices, daily_targets)
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
        effective_by_day[day] = effective
        if not forced_indices:
            add_max_pulses_per_day_constraints(
                model.prob,
                on_vars,
                day_indices,
                max_pulses=max_pulses,
                prefix=f"{cid}_{day.isoformat()}",
                continuing=continuing,
            )
        delivered = _delivery_energy_expr(model, consumer, day_indices)
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
        model.prob += (
            delivered >= effective,
            f"{cid}_thermal_day_{day.isoformat()}",
        )
    return effective_by_day
