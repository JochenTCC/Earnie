"""Live open-loop heat-storage floor + opportunistic headroom (Thermals P2 / 2.7.b).

No MILP store-T SoC: physics stay outside the solver; callers get forced hours and
scalar kWh bounds only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from optimizer.thermal_coupled import (
    heat_storage_enabled,
    normalize_heat_storage,
    step_coupled_hour,
)
from optimizer.thermal_house import (
    DEFAULT_HOUSE_TOLERANCE_C,
    house_capacity_kwh_per_k,
    house_requests_heat,
    step_house_hour,
)
from optimizer.thermal_model import ThermalBand, capacity_kwh_per_k_from_volume, heat_content_kwh

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


def _ww_kw(persons: int) -> float:
    from data.heating_need import warm_water_kwh_week

    return warm_water_kwh_week(int(persons)) / 7.0 / 24.0


@dataclass(frozen=True)
class _HouseLiveParams:
    use_house: bool
    house_c: float
    house_h: float
    house_band_min: float
    house_temp: float
    max_heat: float
    house_target_c: float
    heating_limit_c: float


def _resolve_house_live_params(
    *,
    living_area_m2: float,
    building_mass: str | None,
    target_temp_c: float,
    house_tolerance_c: float | None,
    house_heat_loss_kw_per_k: float | None,
    heating_limit_c: float,
    start_house_temp_c: float | None,
    max_heat: float,
) -> _HouseLiveParams:
    house_temp = float(
        start_house_temp_c if start_house_temp_c is not None else target_temp_c
    )
    target = float(target_temp_c)
    limit = float(heating_limit_c)
    use_house = float(living_area_m2) > 0.0
    if not use_house:
        return _HouseLiveParams(
            False, 0.0, 0.0, target, house_temp, max_heat, target, limit
        )
    if house_heat_loss_kw_per_k is None or float(house_heat_loss_kw_per_k) <= 0.0:
        # H comes from ThermalParameters (reference-year calibration); a short
        # Live forecast alone inflates H by ~8760/n (thermals-p2 §Live store floor).
        raise ValueError(
            "Live-Speicherplan mit Wohnfläche braucht house_heat_loss_kw_per_k "
            "(optimizer.thermal_parameters.house_thermal_parameters)."
        )
    tol = (
        DEFAULT_HOUSE_TOLERANCE_C
        if house_tolerance_c is None
        else max(0.05, float(house_tolerance_c))
    )
    return _HouseLiveParams(
        True,
        house_capacity_kwh_per_k(living_area_m2, building_mass),
        float(house_heat_loss_kw_per_k),
        target - tol,
        house_temp,
        max_heat,
        target,
        limit,
    )


# Recover toward target at most this many K per Euler hour. Full C·ΔT in one hour
# emptied a warm buffer (~5 K drop) and forced WP while T_eq was still above band_max.
_MAX_HOUSE_CLIMB_K_PER_H = 0.1


def _space_heat_demand_kw(
    house: _HouseLiveParams,
    house_temp: float,
    ambient: float,
) -> float:
    """Store draw for space heat: envelope hold / rate-limited climb — not WP dump.

    Using ``max_heat`` as continuous demand emptied a hot buffer (e.g. 67 °C) in
    ~3 h and forced Freigabe while T_eq was still far above setpoint. Pulling
    ``C·(target−T)`` in one hour (leicht Bauweise) caused the same early drain.
    """
    if not house.use_house:
        return 0.0
    if float(ambient) >= house.heating_limit_c - 1e-9:
        return 0.0
    if not house_requests_heat(
        house_temp,
        ambient,
        capacity_kwh_per_k=house.house_c,
        heat_loss_kw_per_k=house.house_h,
        band_min_c=house.house_band_min,
    ):
        return 0.0
    loss = house.house_h * (float(house_temp) - float(ambient))
    delta_k = max(0.0, house.house_target_c - float(house_temp))
    climb = min(delta_k, _MAX_HOUSE_CLIMB_K_PER_H) * house.house_c
    return min(house.max_heat, max(0.0, loss + climb))


def _simulate_store_floor_hours(
    *,
    start_temp_c: float,
    ambient_forecast_c: list[float],
    solar: list[float],
    band: ThermalBand,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    wp_kw: float,
    jaz_f: float,
    ww: float,
    house: _HouseLiveParams,
) -> tuple[list[bool], list[float], float, list[float]]:
    store_temp = float(start_temp_c)
    house_temp = house.house_temp
    forced: list[bool] = []
    electric_by_hour: list[float] = []
    store_temps: list[float] = []
    floor_electric = 0.0
    for hour, ambient_raw in enumerate(ambient_forecast_c):
        ambient = float(ambient_raw)
        space_kw = _space_heat_demand_kw(house, house_temp, ambient)
        result = step_coupled_hour(
            store_temp,
            ambient,
            solar_kw=float(solar[hour]),
            demand_kw=space_kw + ww,
            capacity_kwh_per_k=capacity_kwh_per_k,
            heat_loss_kw_per_k=heat_loss_kw_per_k,
            band=band,
            wp_electric_kw=wp_kw,
            jaz=jaz_f,
        )
        forced.append(bool(result.wp_on))
        electric_by_hour.append(float(result.electric_kwh))
        if result.wp_on:
            floor_electric += float(result.electric_kwh)
        store_temp = result.temp_c
        store_temps.append(float(store_temp))
        if house.use_house:
            house_temp = step_house_hour(
                house_temp,
                ambient,
                heat_in_kw=space_kw,
                capacity_kwh_per_k=house.house_c,
                heat_loss_kw_per_k=house.house_h,
            )
    return forced, electric_by_hour, floor_electric, store_temps


def _apply_t_low_near_term_force(
    forced: list[bool],
    electric_by_hour: list[float],
    floor_electric: float,
    *,
    temp_low_c: float | None,
    band: ThermalBand,
    wp_kw: float,
) -> tuple[list[bool], list[float], float, bool]:
    if temp_low_c is None or float(temp_low_c) >= band.min_c - 1e-9:
        return forced, electric_by_hour, floor_electric, False
    forced = list(forced)
    electric_by_hour = list(electric_by_hour)
    forced[0] = True
    if electric_by_hour[0] <= 1e-12:
        electric_by_hour[0] = wp_kw
        floor_electric += wp_kw
    return forced, electric_by_hour, floor_electric, True


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


SOLAR_SOURCE_NONE = "none"
SOLAR_SOURCE_FORECAST = "open_meteo"
SOLAR_SOURCE_ARCHIVE_FALLBACK = "fallback_archive_year"


def resolve_live_collector_solar_kw(
    thermal: dict,
    house_profile: dict | None,
    horizon: int,
    *,
    start: datetime | None = None,
) -> tuple[list[float], str]:
    """Hourly collector heat into the store (kW_th ≈ kWh per hour) for Live, plus source.

    Open-Meteo forecast irradiance on the collector surface (ThermalHorizon P3).
    If the forecast fails: last full archive year at the same DOY/hour, with a
    warning and source ``fallback_archive_year`` (owner decision 2026-10-15).
    Zeros when ``solar_thermal_area_m2`` is not configured. Raises if area > 0
    but lat/lon cannot be resolved.
    """
    if horizon < 1:
        raise ValueError("horizon muss mindestens 1 sein")
    area_m2 = float(thermal.get("solar_thermal_area_m2", 0.0) or 0.0)
    if area_m2 <= 0.0:
        return [0.0] * horizon, SOLAR_SOURCE_NONE
    from data.modeled_climate import collector_surface_from_thermal
    from data.open_meteo_solar_archive import irradiance_wm2_to_thermal_kwh
    from data.outdoor_forecast import get_hourly_tilted_irradiance_forecast_wm2

    profile = _profile_with_geo(house_profile)
    surface = collector_surface_from_thermal(thermal, profile)
    start_dt = (start or datetime.now()).replace(minute=0, second=0, microsecond=0)
    try:
        wm2 = get_hourly_tilted_irradiance_forecast_wm2(
            horizon=horizon,
            tilt_deg=surface.tilt_deg,
            azimuth_deg=surface.azimuth_deg,
            latitude=float(profile["latitude"]),
            longitude=float(profile["longitude"]),
            start=start_dt,
        )
    except Exception as exc:
        logger.warning(
            "Kollektor-Einstrahlungsprognose fehlgeschlagen (%s) – nutze Vorjahreswerte "
            "(Open-Meteo-Archiv) für den Speicherplan.",
            exc,
        )
        return (
            _archive_year_collector_solar_kw(profile, surface, area_m2, start_dt, horizon),
            SOLAR_SOURCE_ARCHIVE_FALLBACK,
        )
    # Same conversion and rounding as the archive bundle (thermal_kwh_at).
    return (
        [round(irradiance_wm2_to_thermal_kwh(value, area_m2), 6) for value in wm2],
        SOLAR_SOURCE_FORECAST,
    )


def _profile_with_geo(house_profile: dict | None) -> dict:
    profile = dict(house_profile) if isinstance(house_profile, dict) else {}
    if "latitude" not in profile or "longitude" not in profile:
        import config as _cfg

        if getattr(_cfg, "CONFIG", None) is None:
            raise ValueError(
                "solar_thermal_area_m2 > 0 requires house_profile latitude/longitude "
                "or a loaded CONFIG for Live collector irradiance"
            )
        profile.setdefault("latitude", float(_cfg.get("LATITUDE", cast=float)))
        profile.setdefault("longitude", float(_cfg.get("LONGITUDE", cast=float)))
    return profile


def _archive_year_collector_solar_kw(
    profile: dict,
    surface,
    area_m2: float,
    start_dt: datetime,
    horizon: int,
) -> list[float]:
    """Last full archive year at the same DOY/hour (pre-P3 behaviour, now fallback only)."""
    from data.modeled_climate import ModeledClimateContext
    from data.open_meteo_solar_archive import last_full_archive_year

    climate = ModeledClimateContext.for_house_profile(profile, kwp=0.0)
    archive_year = last_full_archive_year()
    bundle = climate._bundle_for_calendar_year(archive_year)
    solar: list[float] = []
    for offset in range(horizon):
        slot = start_dt + timedelta(hours=offset)
        try:
            archive_slot = slot.replace(year=archive_year)
        except ValueError:
            archive_slot = slot.replace(year=archive_year, day=28)
        solar.append(float(bundle.thermal_kwh_at(surface, area_m2, archive_slot)))
    return solar


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


def _thermal_with_nominal(thermal: dict, consumer: dict) -> dict:
    """Same parameter key as baseload (``consumer_annual_kwh``): WP kW on thermal."""
    if "nominal_power_kw" in thermal:
        return thermal
    return {**thermal, "nominal_power_kw": float(consumer.get("nominal_power_kw", 3.0) or 3.0)}


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


@dataclass(frozen=True)
class LiveHousePlan:
    """Live horizon plan of a ``thermal_annual`` consumer without heat storage (P4)."""

    electric_by_hour: list[float]
    # Simulated indoor temperature; empty on the legacy path without Wohnfläche.
    house_temp_c: list[float]
    # Collector credit source (legacy path only); SOLAR_SOURCE_NONE otherwise.
    solar_source: str


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


def plan_live_house_horizon(
    consumer: dict,
    *,
    house_profile: dict,
    ambient_forecast_c: list[float],
    start: datetime | None = None,
) -> LiveHousePlan:
    """House RC + WP over the horizon, same hourly rules as the year sim without store.

    Start = target temperature (no indoor sensor; spec section 7 Q2). Envelope H
    from ``ThermalParameters``. Without Wohnfläche: legacy warm-water need minus
    a per-day collector credit (forecast irradiance, P3).
    """
    from data.heating_need import heat_pump_jaz, warm_water_kwh_week
    from optimizer.thermal_house import _step_hour_direct_wp

    if not ambient_forecast_c:
        raise ValueError("ambient_forecast_c darf nicht leer sein")
    thermal = consumer.get("thermal") or consumer
    jaz = heat_pump_jaz(str(thermal.get("heat_pump_type", "luft")))
    ww_kw = warm_water_kwh_week(int(thermal.get("persons", 2) or 2)) / 7.0 / 24.0
    living = float(thermal.get("living_area_m2", 0.0) or 0.0)
    if living <= 0.0:
        return _plan_live_legacy_ww(
            thermal, house_profile, ambient_forecast_c, ww_kw=ww_kw, jaz=jaz, start=start
        )
    from optimizer.thermal_parameters import house_thermal_parameters

    house_h = house_thermal_parameters(
        _thermal_with_nominal(thermal, consumer), house_profile=house_profile
    ).house_heat_loss_kw_per_k
    wp_kw = max(
        0.1,
        float(thermal.get("nominal_power_kw") or consumer.get("nominal_power_kw") or 3.0),
    )
    target = float(thermal.get("target_temp_c", 21.5) or 21.5)
    tol_raw = thermal.get("house_tolerance_c")
    tol = DEFAULT_HOUSE_TOLERANCE_C if tol_raw in (None, "") else max(0.05, float(tol_raw))
    house_c = house_capacity_kwh_per_k(living, thermal.get("building_mass"))
    house_temp = target
    electric_by_hour: list[float] = []
    house_temps: list[float] = []
    for ambient in ambient_forecast_c:
        house_temp, electric = _step_hour_direct_wp(
            house_temp=house_temp,
            ambient_c=float(ambient),
            house_c=house_c,
            house_h=float(house_h),
            house_band_min=target - tol,
            max_heat_kw=wp_kw * jaz,
            wp_kw=wp_kw,
            ww_electric_kw=ww_kw / jaz if jaz > 0 else 0.0,
        )
        electric_by_hour.append(float(electric))
        house_temps.append(float(house_temp))
    return LiveHousePlan(electric_by_hour, house_temps, SOLAR_SOURCE_NONE)


def _plan_live_legacy_ww(
    thermal: dict,
    house_profile: dict,
    ambient_forecast_c: list[float],
    *,
    ww_kw: float,
    jaz: float,
    start: datetime | None,
) -> LiveHousePlan:
    """Legacy open-loop path (no Wohnfläche): warm water minus collector, netted per day."""
    horizon = len(ambient_forecast_c)
    start_dt = (start or datetime.now()).replace(minute=0, second=0, microsecond=0)
    solar, solar_source = resolve_live_collector_solar_kw(
        thermal, house_profile, horizon, start=start_dt
    )
    offsets_by_day: dict[Any, list[int]] = {}
    for offset in range(horizon):
        day = (start_dt + timedelta(hours=offset)).date()
        offsets_by_day.setdefault(day, []).append(offset)
    electric_by_hour = [0.0] * horizon
    for offsets in offsets_by_day.values():
        heat = ww_kw * len(offsets)
        credit = sum(solar[offset] for offset in offsets)
        net_electric = max(0.0, heat - credit) / jaz if jaz > 0 else 0.0
        for offset in offsets:
            electric_by_hour[offset] = net_electric / len(offsets)
    return LiveHousePlan(electric_by_hour, [], solar_source)


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
