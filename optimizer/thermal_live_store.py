"""Live open-loop heat-storage floor + opportunistic headroom (Thermals P2 / 2.7.b).

No MILP store-T SoC: physics stay outside the solver; callers get forced hours and
scalar kWh bounds only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any

from optimizer.thermal_coupled import (
    heat_storage_enabled,
    normalize_heat_storage,
)
from optimizer.thermal_model import ThermalBand, capacity_kwh_per_k_from_volume, heat_content_kwh
from optimizer.thermal_live_solar import (  # noqa: F401  (re-exported)
    SOLAR_SOURCE_ARCHIVE_FALLBACK,
    SOLAR_SOURCE_FORECAST,
    SOLAR_SOURCE_NONE,
    _archive_year_collector_solar_kw,
    _profile_with_geo,
    resolve_live_collector_solar_kw,
)
from optimizer.thermal_live_floor import (  # noqa: F401  (re-exported)
    _HouseLiveParams,
    _MAX_HOUSE_CLIMB_K_PER_H,
    _apply_t_low_near_term_force,
    _resolve_house_live_params,
    _simulate_store_floor_hours,
    _space_heat_demand_kw,
    _ww_kw,
)
from optimizer.thermal_live_house import (  # noqa: F401  (re-exported)
    LiveHousePlan,
    _plan_live_legacy_ww,
    _thermal_with_nominal,
    plan_live_house_horizon,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeatStorageReadings:
    temp_eq_c: float
    temp_low_c: float | None
    used_measured_eq: bool
    used_measured_low: bool


@dataclass(frozen=True)
class LiveStorePlan:
    forced_hour_flags: list[bool]
    floor_electric_kwh: float
    opp_cap_electric_kwh: float
    start_temp_c: float
    temp_low_c: float | None
    used_measured_eq: bool
    used_measured_low: bool
    band: ThermalBand
    electric_by_hour: list[float]
    store_temp_c: list[float] = field(default_factory=list)
    q_sim_kwh: list[float] = field(default_factory=list)
    # Collector heat input: SOLAR_SOURCE_* (ThermalHorizon P3); "provided" when passed in.
    solar_source: str = "provided"


def resolve_heat_storage_setpoint_band(heat_storage: dict) -> ThermalBand:
    storage = normalize_heat_storage(heat_storage)
    if storage is None:
        raise ValueError("heat_storage ist nicht aktiv (volume_liters <= 0)")
    return ThermalBand(storage["setpoint_c"], storage["tolerance_c"])


def resolve_heat_storage_readings(
    consumer: dict,
    *,
    house_doc: dict | None = None,
    heat_storage: dict | None = None,
) -> HeatStorageReadings:
    """Read T_eq / T_low; missing T_eq falls back to store setpoint."""
    from integrations.ehal_live import fetch_heat_storage_temps

    storage = normalize_heat_storage(
        heat_storage
        if heat_storage is not None
        else (consumer.get("thermal") or {}).get("heat_storage")
        or consumer.get("heat_storage")
    )
    if storage is None:
        raise ValueError("heat_storage ist nicht aktiv")
    band = ThermalBand(storage["setpoint_c"], storage["tolerance_c"])
    measured = fetch_heat_storage_temps(consumer, house_doc=house_doc)
    eq = measured.get("temp_eq_c")
    low = measured.get("temp_low_c")
    used_eq = eq is not None
    return HeatStorageReadings(
        temp_eq_c=float(eq) if used_eq else float(band.setpoint_c),
        temp_low_c=float(low) if low is not None else None,
        used_measured_eq=used_eq,
        used_measured_low=low is not None,
    )
















def plan_live_store_horizon(
    *,
    start_temp_c: float,
    ambient_forecast_c: list[float],
    band: ThermalBand,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    wp_electric_kw: float,
    jaz: float,
    temp_low_c: float | None = None,
    solar_forecast_kw: list[float] | None = None,
    living_area_m2: float = 0.0,
    building_mass: str | None = None,
    target_temp_c: float = 21.5,
    house_tolerance_c: float | None = None,
    house_heat_loss_kw_per_k: float | None = None,
    heating_limit_c: float = 15.0,
    persons: int = 2,
    start_house_temp_c: float | None = None,
    used_measured_eq: bool = False,
    used_measured_low: bool = False,
) -> LiveStorePlan:
    """Bang-bang floor on T_eq plus optional T_low near-term force; opp headroom."""
    horizon = len(ambient_forecast_c)
    if horizon < 1:
        raise ValueError("ambient_forecast_c darf nicht leer sein")
    wp_kw = max(0.1, float(wp_electric_kw))
    jaz_f = max(1e-9, float(jaz))
    solar = list(solar_forecast_kw or [0.0] * horizon)
    if len(solar) < horizon:
        solar = solar + [0.0] * (horizon - len(solar))
    house = _resolve_house_live_params(
        living_area_m2=living_area_m2,
        building_mass=building_mass,
        target_temp_c=target_temp_c,
        house_tolerance_c=house_tolerance_c,
        house_heat_loss_kw_per_k=house_heat_loss_kw_per_k,
        heating_limit_c=heating_limit_c,
        start_house_temp_c=start_house_temp_c,
        max_heat=wp_kw * jaz_f,
    )
    forced, electric_by_hour, floor_electric, store_temps = _simulate_store_floor_hours(
        start_temp_c=start_temp_c,
        ambient_forecast_c=ambient_forecast_c,
        solar=solar,
        band=band,
        capacity_kwh_per_k=capacity_kwh_per_k,
        heat_loss_kw_per_k=heat_loss_kw_per_k,
        wp_kw=wp_kw,
        jaz_f=jaz_f,
        ww=_ww_kw(persons),
        house=house,
    )
    forced, electric_by_hour, floor_electric, low_forced = _apply_t_low_near_term_force(
        forced,
        electric_by_hour,
        floor_electric,
        temp_low_c=temp_low_c,
        band=band,
        wp_kw=wp_kw,
    )
    fill_thermal = max(
        0.0, (band.setpoint_c - float(start_temp_c)) * capacity_kwh_per_k
    )
    opp_cap = max(0.0, fill_thermal / jaz_f - floor_electric)
    q_sim = [
        heat_content_kwh(temp_c, capacity_kwh_per_k) for temp_c in store_temps
    ]
    return LiveStorePlan(
        forced_hour_flags=forced,
        floor_electric_kwh=round(floor_electric, 3),
        opp_cap_electric_kwh=round(opp_cap, 3),
        start_temp_c=round(float(start_temp_c), 3),
        temp_low_c=None if temp_low_c is None else round(float(temp_low_c), 3),
        used_measured_eq=bool(used_measured_eq),
        used_measured_low=bool(used_measured_low) or low_forced,
        band=band,
        electric_by_hour=electric_by_hour,
        store_temp_c=store_temps,
        q_sim_kwh=q_sim,
    )










def plan_live_store_for_thermal_consumer(
    consumer: dict,
    *,
    house_profile: dict,
    ambient_forecast_c: list[float],
    solar_forecast_kw: list[float] | None = None,
    house_doc: dict | None = None,
) -> LiveStorePlan | None:
    """Build Live store plan from a thermal_annual house consumer; None if no store."""
    from data.heating_need import heat_pump_jaz

    thermal = consumer.get("thermal") or consumer
    storage_raw = thermal.get("heat_storage")
    if not heat_storage_enabled(storage_raw):
        return None
    storage = normalize_heat_storage(storage_raw)
    if storage is None:
        return None
    resolved_solar = solar_forecast_kw
    solar_source = "provided"
    if resolved_solar is None:
        resolved_solar, solar_source = resolve_live_collector_solar_kw(
            thermal, house_profile, len(ambient_forecast_c)
        )
    band = ThermalBand(storage["setpoint_c"], storage["tolerance_c"])
    readings = resolve_heat_storage_readings(
        consumer, house_doc=house_doc, heat_storage=storage
    )
    capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
    wp_kw = float(
        thermal.get("nominal_power_kw")
        or consumer.get("nominal_power_kw")
        or 3.0
    )
    living = float(thermal.get("living_area_m2", 0.0) or 0.0)
    house_h = None
    if living > 0.0:
        from optimizer.thermal_parameters import house_thermal_parameters

        house_h = house_thermal_parameters(
            _thermal_with_nominal(thermal, consumer), house_profile=house_profile
        ).house_heat_loss_kw_per_k
    plan = plan_live_store_horizon(
        start_temp_c=readings.temp_eq_c,
        ambient_forecast_c=ambient_forecast_c,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=float(storage["heat_loss_kw_per_k"]),
        wp_electric_kw=wp_kw,
        jaz=heat_pump_jaz(str(thermal.get("heat_pump_type", "luft"))),
        temp_low_c=readings.temp_low_c,
        solar_forecast_kw=resolved_solar,
        living_area_m2=living,
        building_mass=thermal.get("building_mass"),
        target_temp_c=float(thermal.get("target_temp_c", 21.5) or 21.5),
        house_tolerance_c=thermal.get("house_tolerance_c"),
        house_heat_loss_kw_per_k=house_h,
        heating_limit_c=float(thermal.get("heating_limit_c", 15.0) or 15.0),
        persons=int(thermal.get("persons", 2) or 2),
        used_measured_eq=readings.used_measured_eq,
        used_measured_low=readings.used_measured_low,
    )
    return replace(plan, solar_source=solar_source)




def live_store_plan_for_matrix(
    source: dict,
    house_profile: dict,
    matrix: list,
) -> LiveStorePlan | None:
    """Live store plan over the matrix horizon; built once per Live cycle.

    Flex contexts, horizon targets and both MILP runs of a cycle share one plan
    (one set of readings + forecast) via ``optimizer.live_cycle_scope``.
    """
    thermal = source.get("thermal") or source
    if not heat_storage_enabled(thermal.get("heat_storage")) or not matrix:
        return None
    from optimizer.charging_context import matrix_slot_datetime
    from optimizer.live_cycle_scope import cycle_memo
    from optimizer.thermal_targets import thermal_horizon_hours_from_slots
    from optimizer.thermal_year_cache import fingerprint_json

    horizon_h = thermal_horizon_hours_from_slots(len(matrix))
    key = (
        "live_store_plan",
        fingerprint_json(source),
        horizon_h,
        matrix_slot_datetime(matrix, 0).isoformat(),
    )
    return cycle_memo(
        key, lambda: _build_live_store_plan(source, house_profile, horizon_h)
    )


def _live_ambient_forecast(horizon_h: int) -> list[float]:
    """Outdoor forecast for the Live horizon; constant live reading if Open-Meteo fails."""
    from data.outdoor_forecast import get_outdoor_forecast_with_fallback

    fallback_ambient = 10.0
    try:
        from integrations.ehal_live import read_optional_temp_c as _read_optional_temp_c
        from settings.ehal_marker_resolve import marker_sens_temperature_outside

        live_amb = _read_optional_temp_c(marker_sens_temperature_outside(house_doc=None))
        if live_amb is not None:
            fallback_ambient = float(live_amb)
    except Exception:
        pass
    ambient_forecast, _src = get_outdoor_forecast_with_fallback(
        horizon=horizon_h,
        fallback_ambient_c=fallback_ambient,
    )
    return ambient_forecast


def _build_live_store_plan(
    source: dict,
    house_profile: dict,
    horizon_h: int,
) -> LiveStorePlan | None:
    return plan_live_store_for_thermal_consumer(
        source,
        house_profile=house_profile,
        ambient_forecast_c=_live_ambient_forecast(horizon_h),
        house_doc=None,
    )


def hourly_electric_to_slot_energy_kwh(
    matrix: list, electric_by_hour: list[float]
) -> list[float]:
    """WP electric kWh per matrix slot from hourly electric (wall-clock hour from horizon start)."""
    from optimizer.charging_context import matrix_slot_datetime
    from optimizer.slot_duration import energy_kwh_from_kw

    if not matrix:
        return []
    start = matrix_slot_datetime(matrix, 0)
    energies: list[float] = []
    for index in range(len(matrix)):
        hour_offset = int((matrix_slot_datetime(matrix, index) - start).total_seconds() // 3600)
        if 0 <= hour_offset < len(electric_by_hour):
            # electric_by_hour is kWh per hour == mean kW over that hour.
            energies.append(float(energy_kwh_from_kw([electric_by_hour[hour_offset]])))
        else:
            energies.append(0.0)
    return energies


def live_store_slot_energy_kwh(matrix: list, plan: LiveStorePlan) -> list[float]:
    """WP electric kWh per matrix slot from the store plan."""
    return hourly_electric_to_slot_energy_kwh(matrix, plan.electric_by_hour)




def live_house_plan_for_matrix(
    source: dict,
    house_profile: dict,
    matrix: list,
) -> LiveHousePlan | None:
    """Horizon plan without heat storage; None when a store is configured. Once per cycle."""
    thermal = source.get("thermal") or source
    if heat_storage_enabled(thermal.get("heat_storage")) or not matrix:
        return None
    from optimizer.charging_context import matrix_slot_datetime
    from optimizer.live_cycle_scope import cycle_memo
    from optimizer.thermal_targets import thermal_horizon_hours_from_slots
    from optimizer.thermal_year_cache import fingerprint_json

    horizon_h = thermal_horizon_hours_from_slots(len(matrix))
    key = (
        "live_house_plan",
        fingerprint_json(source),
        horizon_h,
        matrix_slot_datetime(matrix, 0).isoformat(),
    )
    return cycle_memo(
        key,
        lambda: plan_live_house_horizon(
            source,
            house_profile=house_profile,
            ambient_forecast_c=_live_ambient_forecast(horizon_h),
        ),
    )






def map_forced_hours_to_slot_indices(
    matrix: list,
    forced_hour_flags: list[bool],
    *,
    eligible_indices: list[int] | None = None,
) -> list[int]:
    """Map hour flags onto matrix QH indices (wall-clock hour match from horizon start)."""
    from optimizer.charging_context import matrix_slot_datetime

    if not matrix or not forced_hour_flags:
        return []
    eligible = set(eligible_indices) if eligible_indices is not None else None
    start = matrix_slot_datetime(matrix, 0)
    forced_slots: list[int] = []
    for index, _row in enumerate(matrix):
        if eligible is not None and index not in eligible:
            continue
        slot_dt = matrix_slot_datetime(matrix, index)
        hour_offset = int((slot_dt - start).total_seconds() // 3600)
        if hour_offset < 0 or hour_offset >= len(forced_hour_flags):
            continue
        if forced_hour_flags[hour_offset]:
            forced_slots.append(index)
    return forced_slots


def live_min_kwh_by_day(matrix: list, plan: LiveStorePlan) -> dict[Any, float]:
    """Flexible Live day lower bound: opportunistic headroom to setpoint on first day.

    Bang-bang floor energy is enforced only via ``forced_indices`` (correct timing).
    Putting floor kWh into a movable day budget made MILP heat while the store was
    still hot (e.g. 60 °C) to satisfy later floor hours — including hours outside
    the MILP window.
    """
    from optimizer.charging_context import matrix_slot_datetime

    if not matrix:
        return {}
    if plan.opp_cap_electric_kwh <= 1e-9:
        return {}
    first_day = matrix_slot_datetime(matrix, 0).date()
    return {first_day: round(float(plan.opp_cap_electric_kwh), 3)}


def build_heat_storage_observability(
    consumer: dict,
    *,
    house_profile: dict,
    ambient_forecast_c: list[float],
    house_doc: dict | None = None,
    solar_forecast_kw: list[float] | None = None,
) -> dict[str, Any] | None:
    """Snapshot for optimization_history: T_eq/T_low + Q_meas/Q_sim."""
    plan = plan_live_store_for_thermal_consumer(
        consumer,
        house_profile=house_profile,
        ambient_forecast_c=ambient_forecast_c,
        solar_forecast_kw=solar_forecast_kw,
        house_doc=house_doc,
    )
    if plan is None:
        return None
    thermal = consumer.get("thermal") or consumer
    storage = normalize_heat_storage(thermal.get("heat_storage"))
    if storage is None:
        return None
    capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
    q_meas = heat_content_kwh(plan.start_temp_c, capacity)
    q_sim = (
        float(plan.q_sim_kwh[0])
        if plan.q_sim_kwh
        else heat_content_kwh(plan.start_temp_c, capacity)
    )
    return {
        "consumer_id": consumer.get("id"),
        "kind": "heat_storage",
        "readings_c": {
            "temp_eq": plan.start_temp_c,
            "temp_low": plan.temp_low_c,
            "setpoint": plan.band.setpoint_c,
            "tolerance": plan.band.tolerance_c,
            "band_min": plan.band.min_c,
            "band_max": plan.band.max_c,
        },
        "heat_content_kwh": {
            "q_meas": round(q_meas, 3),
            "q_sim": round(q_sim, 3),
        },
        "model": {
            "capacity_kwh_per_k": round(capacity, 4),
            "volume_liters": float(storage["volume_liters"]),
            "heat_loss_kw_per_k": float(storage["heat_loss_kw_per_k"]),
        },
        "used_measured_eq": plan.used_measured_eq,
        "used_measured_low": plan.used_measured_low,
        "collector_solar_source": plan.solar_source,
        "horizon_q_sim_kwh": [round(v, 3) for v in plan.q_sim_kwh],
    }


def collect_heat_storage_observability(
    consumers: list[dict],
    *,
    house_profile: dict,
    horizon: int = 24,
    house_doc: dict | None = None,
) -> list[dict[str, Any]]:
    """Observability for thermal_annual consumers with active heat_storage."""
    from data.outdoor_forecast import get_outdoor_forecast_with_fallback

    results: list[dict[str, Any]] = []
    fallback_ambient = 10.0
    try:
        from integrations.ehal_live import read_optional_temp_c as _read_optional_temp_c
        from settings.ehal_marker_resolve import marker_sens_temperature_outside

        live_amb = _read_optional_temp_c(marker_sens_temperature_outside(house_doc=house_doc))
        if live_amb is not None:
            fallback_ambient = float(live_amb)
    except Exception:
        pass
    ambient_forecast, _src = get_outdoor_forecast_with_fallback(
        horizon=max(1, int(horizon)),
        fallback_ambient_c=fallback_ambient,
    )
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        if consumer.get("type") != "thermal_annual":
            continue
        thermal = consumer.get("thermal") or consumer
        if not heat_storage_enabled(thermal.get("heat_storage")):
            continue
        cid = consumer.get("id") or "?"
        try:
            item = build_heat_storage_observability(
                consumer,
                house_profile=house_profile,
                ambient_forecast_c=ambient_forecast,
                house_doc=house_doc,
            )
            if item is not None:
                results.append(item)
        except Exception as exc:
            results.append(
                {
                    "consumer_id": cid,
                    "kind": "heat_storage",
                    "error": str(exc),
                }
            )
    return results
