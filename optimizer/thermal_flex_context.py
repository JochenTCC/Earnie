"""MILP-Zeitfenster und Tagesziele für Haus-Wärme (thermal_annual / Thermals P1a).

Import facade: basics live in ``thermal_flex_base``, the MILP constraints in
``thermal_flex_milp`` / ``thermal_flex_store``; this module keeps the context resolution.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from optimizer.charging_context import matrix_slot_datetime
from optimizer.hp_store import HP_STORE_CONTEXT_KEY, hp_store_balance
from optimizer.rod_store import STORE_BALANCE_CONTEXT_KEY, rod_store_balance
from optimizer.thermal_flex_base import (  # noqa: F401  (re-exported)
    LIVE_STORE_PLAN_KEY,
    THERMAL_MAX_ON_HOURS,
    THERMAL_MAX_PULSES_PER_DAY,
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
    thermal_flex_window,
)
from optimizer.thermal_flex_milp import (  # noqa: F401  (re-exported)
    _add_live_rod_pulse_limit,
    _add_one_thermal_flex_consumer,
    _force_rod_off_outside,
    _thermal_day_want_kwh,
    add_thermal_flex_constraints,
)
from optimizer.thermal_flex_store import (  # noqa: F401  (re-exported)
    _add_fuel_parent_rod_caps,
    _add_hp_store_balance,
    _add_live_store_consumer,
    _add_rod_store_balance,
    _hp_drain_scaled_to_days,
    _store_heat_expr,
    _store_inflow_exprs,
)
from optimizer.thermal_store_model import add_store_level  # noqa: F401  (re-exported)

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext

logger = logging.getLogger(__name__)


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
    from optimizer.absent_mode import resolve_absent_status
    from optimizer.live_cycle_scope import is_live_thermal_planning

    thermal_by_id = {
        str(item["id"]): item
        for item in _house_thermal_consumers(house_profile)
    }
    live_absent = False
    is_live = is_live_thermal_planning(matrix)
    if is_live:
        live_absent = bool(resolve_absent_status(house_profile)["effective"])
    run = {
        "matrix": matrix,
        "house_profile": house_profile,
        "climate": climate,
        "is_live": is_live,
        "live_absent": live_absent,
        "rod_store_start_kwh": rod_store_start_kwh,
        "hp_store_start_kwh": hp_store_start_kwh,
    }
    contexts: dict[str, dict] = {}
    for consumer in consumers:
        if is_heating_rod_consumer(consumer):
            parent = thermal_by_id.get(str(consumer["parent_id"]))
            if parent is not None:
                contexts[str(consumer["id"])] = _rod_context(run, consumer, parent)
            continue
        if not is_thermal_flex_consumer(consumer):
            continue
        cid = str(consumer["id"])
        source = thermal_by_id.get(cid)
        if source:
            contexts[cid] = _heat_source_context(run, consumer, source)
    return contexts


def _rod_context(run: dict, rod: dict, parent: dict) -> dict:
    """Live: pulse limit / fuel cap of the rod; SE: the rod's store balance."""
    matrix, house_profile = run["matrix"], run["house_profile"]
    if run["is_live"]:
        return _live_rod_context(matrix, rod, parent, house_profile)
    return {
        STORE_BALANCE_CONTEXT_KEY: rod_store_balance(
            matrix,
            str(rod["id"]),
            parent,
            house_profile,
            start_levels_kwh=run["rod_store_start_kwh"],
            climate=run["climate"],
        )
    }


def _heat_source_context(run: dict, consumer: dict, source: dict) -> dict:
    """Day targets / slot energy of one thermal_annual consumer (Live: its horizon plan)."""
    from optimizer.absent_mode import thermal_source_with_live_absent

    matrix, house_profile, is_live = run["matrix"], run["house_profile"], run["is_live"]
    source = thermal_source_with_live_absent(
        source, live_absent_active=run["live_absent"]
    )
    live_ctx = (
        _live_store_flex_overlay(matrix, source, house_profile, consumer)
        if is_live
        else None
    )
    if live_ctx is not None:
        # Live + heat storage: horizon plan only, no year profile (ThermalHorizon P2).
        return live_ctx
    if is_live:
        # Live without storage: house-only horizon plan (ThermalHorizon P4).
        slot_energy = _live_house_slot_energy_kwh(matrix, source, house_profile)
    else:
        slot_energy = _slot_aligned_thermal_energy_kwh(
            source, matrix, climate=run["climate"]
        )
    ctx = {
        "daily_targets": _daily_targets_from_slot_energy(matrix, slot_energy),
        "slot_energy_kwh": slot_energy,
        "targets_slot_aligned": True,
    }
    if not is_live and _heat_source_is_electric(source):
        ctx[HP_STORE_CONTEXT_KEY] = hp_store_balance(
            str(consumer["id"]),
            source,
            slot_energy,
            _heat_source_efficiency(source),
            start_levels_kwh=run["hp_store_start_kwh"],
        )
    return ctx


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

