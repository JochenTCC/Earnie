"""Thermals P2 — linear house ↔ heat-storage ↔ solar coupling (WP charges store)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from optimizer.thermal_model import (
    ThermalBand,
    capacity_kwh_per_k_from_volume,
    compute_heat_loss_kw,
)

# Absolute store ceiling (°C): solar input capped only above this; WP stops at setpoint.
HEAT_STORAGE_ABS_MAX_C = 95.0


def heat_storage_enabled(heat_storage: dict | None) -> bool:
    """True when optional nested heat_storage has a positive volume."""
    if not isinstance(heat_storage, dict):
        return False
    return float(heat_storage.get("volume_liters", 0.0) or 0.0) > 0.0


def normalize_heat_storage(raw: dict | None) -> dict | None:
    """Normalize heat_storage dict; return None when disabled."""
    if not isinstance(raw, dict):
        return None
    volume = float(raw.get("volume_liters", 0.0) or 0.0)
    if volume <= 0.0:
        return None
    return {
        "volume_liters": volume,
        "heat_loss_kw_per_k": max(0.0, float(raw.get("heat_loss_kw_per_k", 0.02) or 0.02)),
        "setpoint_c": float(raw.get("setpoint_c", 45.0)),
        "tolerance_c": max(0.1, float(raw.get("tolerance_c", 5.0) or 5.0)),
    }


@dataclass(frozen=True)
class CoupledHourResult:
    temp_c: float
    electric_kwh: float
    solar_kwh: float
    demand_kwh: float
    wp_on: bool


def _store_next_temp(
    temp_c: float,
    *,
    heat_in_kw: float,
    demand_kw: float,
    ambient_c: float,
    heat_loss_kw_per_k: float,
    capacity_kwh_per_k: float,
) -> float:
    loss = compute_heat_loss_kw(temp_c, ambient_c, heat_loss_kw_per_k)
    return float(temp_c) + (heat_in_kw - demand_kw - loss) / capacity_kwh_per_k


def _max_heat_in_for_limit(
    temp_c: float,
    limit_c: float,
    *,
    demand_kw: float,
    ambient_c: float,
    heat_loss_kw_per_k: float,
    capacity_kwh_per_k: float,
) -> float:
    """Max heat_in (kW) so end-of-hour store T equals limit_c."""
    loss = compute_heat_loss_kw(temp_c, ambient_c, heat_loss_kw_per_k)
    return (limit_c - temp_c) * capacity_kwh_per_k + demand_kw + loss


def step_coupled_hour(
    temp_c: float,
    ambient_c: float,
    *,
    solar_kw: float,
    demand_kw: float,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    band: ThermalBand,
    wp_electric_kw: float,
    jaz: float,
) -> CoupledHourResult:
    """One Euler hour: solar + demand on store; WP hard-on below min, off above setpoint.

    Store may float up to ``HEAT_STORAGE_ABS_MAX_C`` from solar; WP heat is capped at
    ``band.setpoint_c``. Solar input is reduced only when T would exceed the abs max.
    """
    if capacity_kwh_per_k <= 0:
        raise ValueError("capacity_kwh_per_k muss > 0 sein")
    if jaz <= 0:
        raise ValueError("jaz muss > 0 sein")
    wp_electric = max(0.0, float(wp_electric_kw))
    wp_heat_kw = wp_electric * float(jaz)
    solar = max(0.0, float(solar_kw))
    demand = max(0.0, float(demand_kw))
    step_kw = dict(
        demand_kw=demand,
        ambient_c=ambient_c,
        heat_loss_kw_per_k=heat_loss_kw_per_k,
        capacity_kwh_per_k=capacity_kwh_per_k,
    )
    max_95 = _max_heat_in_for_limit(temp_c, HEAT_STORAGE_ABS_MAX_C, **step_kw)
    max_set = _max_heat_in_for_limit(temp_c, band.setpoint_c, **step_kw)
    solar_for_floor = min(solar, max(0.0, max_95))
    wp_on = _store_next_temp(temp_c, heat_in_kw=solar_for_floor, **step_kw) < (
        band.min_c - 1e-9
    )
    wp_heat_used = 0.0
    electric = 0.0
    if wp_on:
        wp_heat_used = min(wp_heat_kw, max(0.0, max_set))
        if wp_heat_used <= 1e-12:
            wp_on = False
            wp_heat_used = 0.0
        elif wp_heat_kw > 1e-12:
            electric = wp_electric * (wp_heat_used / wp_heat_kw)
    solar_used = min(solar, max(0.0, max_95 - wp_heat_used))
    next_temp = _store_next_temp(
        temp_c, heat_in_kw=wp_heat_used + solar_used, **step_kw
    )
    if next_temp > HEAT_STORAGE_ABS_MAX_C + 1e-9:
        next_temp = HEAT_STORAGE_ABS_MAX_C
    return CoupledHourResult(
        temp_c=next_temp,
        electric_kwh=electric,
        solar_kwh=solar_used,
        demand_kwh=demand,
        wp_on=wp_on,
    )


def _hourly_solar_from_daily(
    solar_day_kwh: float,
    *,
    daylight_start: int = 8,
    daylight_hours: int = 10,
) -> list[float]:
    """Spread daily collector yield over daytime hours."""
    hours = [0.0] * 24
    if solar_day_kwh <= 0.0 or daylight_hours <= 0:
        return hours
    per = float(solar_day_kwh) / float(daylight_hours)
    for offset in range(daylight_hours):
        hour = (daylight_start + offset) % 24
        hours[hour] = per
    return hours


def _group_hourly_by_day(
    hourly_temperature_c: pd.Series,
    hourly_collector_wm2: pd.Series | None,
    area_m2: float,
) -> list[tuple[date, list[float], list[float]]]:
    """Build (day, ambient[24], solar_kw[24]) rows from hourly climate."""
    from data.open_meteo_solar_archive import irradiance_wm2_to_thermal_kwh

    if hourly_temperature_c.empty:
        raise ValueError("hourly_temperature_c ist leer.")
    by_day_temp: dict[date, list[tuple[int, float]]] = {}
    for ts, temp in hourly_temperature_c.items():
        stamp = pd.Timestamp(ts)
        day = stamp.date()
        by_day_temp.setdefault(day, []).append((int(stamp.hour), float(temp)))

    by_day_solar: dict[date, list[float]] = {}
    if area_m2 > 0.0 and hourly_collector_wm2 is not None and not hourly_collector_wm2.empty:
        for ts, wm2 in hourly_collector_wm2.items():
            stamp = pd.Timestamp(ts)
            day = stamp.date()
            if day not in by_day_solar:
                by_day_solar[day] = [0.0] * 24
            by_day_solar[day][int(stamp.hour)] += irradiance_wm2_to_thermal_kwh(
                wm2, area_m2
            )

    rows: list[tuple[date, list[float], list[float]]] = []
    for day in sorted(by_day_temp):
        samples = by_day_temp[day]
        mean_t = sum(t for _, t in samples) / len(samples)
        amb = [mean_t] * 24
        for hour, temp in samples:
            amb[hour] = temp
        solar = by_day_solar.get(day, [0.0] * 24)
        rows.append((day, amb, solar))
    return rows


@dataclass(frozen=True)
class CoupledYearResult:
    """Daily WP electric kWh plus hourly store and house temperatures."""

    daily_electric_kwh: list[float]
    hourly_store_temp_c: list[float]
    hourly_house_temp_c: list[float] = field(default_factory=list)


def coupled_year_result(
    *,
    living_area_m2: float,
    building_class: int,
    heat_pump_type: str,
    persons: int,
    latitude: float,
    longitude: float,
    target_temp_c: float,
    heating_limit_c: float,
    heat_storage: dict,
    hp_electric_kw: float,
    daily_temps: list[float] | None = None,
    daily_radiation_mj: list[float] | None = None,
    hourly_temperature_c: pd.Series | None = None,
    hourly_collector_wm2: pd.Series | None = None,
    hwb_kwh_m2: float | None = None,
    solar_thermal_area_m2: float = 0.0,
    solar_thermal_tilt_deg: float = 18.0,
    solar_thermal_azimuth_deg: float = 0.0,
    start_temp_c: float | None = None,
    building_mass: str | None = None,
    house_tolerance_c: float | None = None,
    house_heat_loss_kw_per_k: float | None = None,
    start_house_temp_c: float | None = None,
) -> CoupledYearResult:
    """Run coupled store + house RC; return daily electric and hourly temps."""
    from optimizer.thermal_house import house_year_result

    storage = normalize_heat_storage(heat_storage)
    if storage is None:
        raise ValueError("heat_storage.volume_liters muss > 0 sein")

    result = house_year_result(
        living_area_m2=living_area_m2,
        building_class=building_class,
        heat_pump_type=heat_pump_type,
        persons=persons,
        latitude=latitude,
        longitude=longitude,
        target_temp_c=target_temp_c,
        heating_limit_c=heating_limit_c,
        hp_electric_kw=hp_electric_kw,
        heat_storage=storage,
        daily_temps=daily_temps,
        daily_radiation_mj=daily_radiation_mj,
        hourly_temperature_c=hourly_temperature_c,
        hourly_collector_wm2=hourly_collector_wm2,
        hwb_kwh_m2=hwb_kwh_m2,
        solar_thermal_area_m2=solar_thermal_area_m2,
        solar_thermal_tilt_deg=solar_thermal_tilt_deg,
        solar_thermal_azimuth_deg=solar_thermal_azimuth_deg,
        building_mass=building_mass,
        house_tolerance_c=house_tolerance_c,
        house_heat_loss_kw_per_k=house_heat_loss_kw_per_k,
        start_house_temp_c=start_house_temp_c,
        start_store_temp_c=start_temp_c,
    )
    return CoupledYearResult(
        daily_electric_kwh=result.daily_electric_kwh,
        hourly_store_temp_c=result.hourly_store_temp_c,
        hourly_house_temp_c=result.hourly_house_temp_c,
    )


def coupled_daily_electric_kwh(**kwargs) -> list[float]:
    """WP electric kWh per calendar day via coupled store + house RC.

    Keyword arguments match ``coupled_year_result``.
    """
    return coupled_year_result(**kwargs).daily_electric_kwh


def coupled_hourly_store_temp_c(**kwargs) -> list[float]:
    """Hourly heat-storage temperature (°C) from the coupled simulation.

    Keyword arguments match ``coupled_year_result``.
    """
    return coupled_year_result(**kwargs).hourly_store_temp_c


def coupled_hourly_house_temp_c(**kwargs) -> list[float]:
    """Hourly house indoor temperature (°C) from the coupled simulation."""
    return coupled_year_result(**kwargs).hourly_house_temp_c
