"""Thermischer Jahresbedarf (WP-Strom) — extrahiert aus config/prognosis-heating-need.py."""
from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

_BUILDING_KWH_M2 = {1: 15.0, 2: 45.0, 3: 80.0, 4: 130.0}
_JAZ = {"luft": 3.5, "erde": 4.3}
_SOLAR_THERMAL_EFFICIENCY = 0.40
_CLIMATE_CACHE = Path("data/cache/heating_climate_default.json")


def specific_heating_kwh_m2(
    building_class: int,
    *,
    hwb_kwh_m2: float | None = None,
) -> float:
    if hwb_kwh_m2 is not None and float(hwb_kwh_m2) > 0:
        return float(hwb_kwh_m2)
    return _BUILDING_KWH_M2.get(int(building_class), 80.0)


def heat_pump_jaz(heat_pump_type: str) -> float:
    return _JAZ.get(str(heat_pump_type).lower().strip(), 3.5)


def warm_water_kwh_week(persons: int) -> float:
    if persons <= 0:
        return 0.0
    return persons * 2.0 * 7.0


def weekly_heating_factors(
    daily_temps: list[float],
    target_temp_c: float,
    heating_limit_c: float,
) -> list[float]:
    if not daily_temps or len(daily_temps) < 364:
        return [1.0 / 52] * 52
    hdd = [
        max(0.0, target_temp_c - t) if t < heating_limit_c else 0.0 for t in daily_temps
    ]
    weekly = [sum(hdd[i * 7 : (i + 1) * 7]) for i in range(52)]
    total = sum(weekly)
    if total == 0:
        return [1.0 / 52] * 52
    return [h / total for h in weekly]


def daily_transposition_factor(
    lat: float,
    day_of_year: int,
    tilt: float,
    azimuth: float,
) -> float:
    """Geometrischer Umrechnungsfaktor von horizontaler zu geneigter Fläche."""
    lat_rad, tilt_rad, az_rad = map(math.radians, [lat, tilt, azimuth])
    decl = math.radians(23.45 * math.sin(math.radians(360 / 365 * (284 + day_of_year))))
    cos_zenith = math.cos(lat_rad - decl)
    cos_zenith = max(0.1, cos_zenith)
    cos_theta = (
        math.cos(lat_rad - decl) * math.cos(tilt_rad)
        + math.sin(lat_rad - decl) * math.sin(tilt_rad) * math.cos(az_rad)
    )
    cos_theta = max(0.0, cos_theta)
    return 0.5 * (cos_theta / cos_zenith) + 0.5 * ((1.0 + math.cos(tilt_rad)) / 2.0)


def weekly_solar_thermal_kwh(
    radiation_mj_year: list[float],
    week_idx: int,
    area_m2: float,
    lat: float,
    tilt: float,
    azimuth: float,
) -> float:
    """Thermischer Solarertrag einer Woche (kWh_th) mit Tilt und Azimuth."""
    if not radiation_mj_year or area_m2 <= 0.0:
        return 0.0
    week_yield = 0.0
    for day_offset in range(7):
        day_of_year = (week_idx * 7) + day_offset + 1
        if day_of_year > len(radiation_mj_year):
            break
        horizontal_kwh = radiation_mj_year[day_of_year - 1] / 3.6
        r_factor = daily_transposition_factor(lat, day_of_year, tilt, azimuth)
        week_yield += (horizontal_kwh * r_factor) * area_m2 * _SOLAR_THERMAL_EFFICIENCY
    return week_yield


def fetch_climate(lat: float, lon: float, year: int = 2025) -> dict:
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
        f"&start_date={year}-01-01&end_date={year}-12-31"
        f"&daily=temperature_2m_mean,shortwave_radiation_sum&timezone=auto"
    )
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode())


def _parse_climate_daily(data: dict) -> tuple[list[float], list[float]]:
    daily = data.get("daily", {})
    temps = daily.get("temperature_2m_mean", [])
    radiation = daily.get("shortwave_radiation_sum", [])
    if len(temps) < 364:
        raise ValueError("Klimadaten: temperature_2m_mean unvollständig.")
    if len(radiation) < 364:
        raise ValueError("Klimadaten: shortwave_radiation_sum unvollständig.")
    return [float(t) for t in temps], [float(r) for r in radiation]


def load_climate_fixture() -> list[float]:
    temps, _ = load_climate_daily()
    return temps


def load_climate_daily(*, lat: float | None = None, lon: float | None = None) -> tuple[list[float], list[float]]:
    """Lädt Tages-Temperaturen und Globalstrahlung (Offline-Fixture)."""
    del lat, lon
    if not _CLIMATE_CACHE.is_file():
        raise FileNotFoundError(
            f"Klimadaten-Fixture fehlt: {_CLIMATE_CACHE}. "
            "Für Tests data/cache/heating_climate_default.json anlegen."
        )
    with _CLIMATE_CACHE.open(encoding="utf-8") as handle:
        return _parse_climate_daily(json.load(handle))


def _net_electric_kwh_week(
    heat_week_kwh: float,
    ww_week_kwh: float,
    solar_week_kwh: float,
    jaz: float,
) -> float:
    gross_heat = heat_week_kwh + ww_week_kwh
    net_heat = max(0.0, gross_heat - solar_week_kwh)
    return net_heat / jaz


def weekly_electric_kwh(
    *,
    living_area_m2: float,
    building_class: int,
    heat_pump_type: str,
    persons: int,
    latitude: float,
    longitude: float,
    target_temp_c: float,
    heating_limit_c: float,
    daily_temps: list[float] | None = None,
    daily_radiation_mj: list[float] | None = None,
    hwb_kwh_m2: float | None = None,
    solar_thermal_area_m2: float = 0.0,
    solar_thermal_tilt_deg: float = 18.0,
    solar_thermal_azimuth_deg: float = 0.0,
) -> list[float]:
    """Elektrischer WP-Bedarf pro Kalenderwoche (kWh)."""
    area_m2 = float(solar_thermal_area_m2)
    if daily_temps is None or (area_m2 > 0.0 and daily_radiation_mj is None):
        fixture_temps, fixture_radiation = load_climate_daily(
            lat=latitude,
            lon=longitude,
        )
        if daily_temps is None:
            daily_temps = fixture_temps
        if area_m2 > 0.0 and daily_radiation_mj is None:
            daily_radiation_mj = fixture_radiation
    if area_m2 > 0.0 and not daily_radiation_mj:
        raise ValueError(
            "solar_thermal_area_m2 > 0 erfordert shortwave_radiation_sum in den Klimadaten."
        )
    annual_heat = living_area_m2 * specific_heating_kwh_m2(
        building_class,
        hwb_kwh_m2=hwb_kwh_m2,
    )
    factors = weekly_heating_factors(daily_temps, target_temp_c, heating_limit_c)
    ww_week = warm_water_kwh_week(persons)
    jaz = heat_pump_jaz(heat_pump_type)
    weekly: list[float] = []
    for week_idx, factor in enumerate(factors):
        heat_week = annual_heat * factor
        solar_week = 0.0
        if area_m2 > 0.0 and daily_radiation_mj:
            solar_week = weekly_solar_thermal_kwh(
                daily_radiation_mj,
                week_idx,
                area_m2,
                latitude,
                float(solar_thermal_tilt_deg),
                float(solar_thermal_azimuth_deg),
            )
        weekly.append(
            round(_net_electric_kwh_week(heat_week, ww_week, solar_week, jaz), 3)
        )
    return weekly


def _thermal_hwb_value(thermal: dict) -> float | None:
    hwb = thermal.get("hwb_kwh_m2")
    return float(hwb) if hwb not in (None, "") else None


def heating_params_from_thermal(thermal: dict) -> dict:
    """Gemeinsame Parameter für estimate_annual_kwh / weekly_electric_kwh."""
    return {
        "living_area_m2": float(thermal.get("living_area_m2", 0.0)),
        "building_class": int(thermal.get("building_class", 3)),
        "heat_pump_type": str(thermal.get("heat_pump_type", "luft")),
        "persons": int(thermal.get("persons", 2)),
        "latitude": float(thermal.get("latitude", 48.0)),
        "longitude": float(thermal.get("longitude", 10.0)),
        "target_temp_c": float(thermal.get("target_temp_c", 21.5)),
        "heating_limit_c": float(thermal.get("heating_limit_c", 15.0)),
        "hwb_kwh_m2": _thermal_hwb_value(thermal),
        "solar_thermal_area_m2": float(thermal.get("solar_thermal_area_m2", 0.0) or 0.0),
        "solar_thermal_tilt_deg": float(thermal.get("solar_thermal_tilt_deg", 18.0)),
        "solar_thermal_azimuth_deg": float(thermal.get("solar_thermal_azimuth_deg", 0.0)),
    }


def estimate_annual_kwh(
    *,
    living_area_m2: float,
    building_class: int,
    heat_pump_type: str,
    persons: int,
    latitude: float,
    longitude: float,
    target_temp_c: float = 21.5,
    heating_limit_c: float = 15.0,
    hwb_kwh_m2: float | None = None,
    solar_thermal_area_m2: float = 0.0,
    solar_thermal_tilt_deg: float = 18.0,
    solar_thermal_azimuth_deg: float = 0.0,
) -> float:
    if living_area_m2 <= 0:
        return 0.0
    weekly = weekly_electric_kwh(
        living_area_m2=living_area_m2,
        building_class=building_class,
        heat_pump_type=heat_pump_type,
        persons=persons,
        latitude=latitude,
        longitude=longitude,
        target_temp_c=target_temp_c,
        heating_limit_c=heating_limit_c,
        hwb_kwh_m2=hwb_kwh_m2,
        solar_thermal_area_m2=solar_thermal_area_m2,
        solar_thermal_tilt_deg=solar_thermal_tilt_deg,
        solar_thermal_azimuth_deg=solar_thermal_azimuth_deg,
    )
    return round(sum(weekly), 3)


def hourly_profile_for_year(
    weekly_kwh: list[float],
    *,
    hours_per_year: int = 8760,
) -> list[float]:
    """Verteilt Wochenwerte gleichmäßig auf Stunden (8760)."""
    if len(weekly_kwh) != 52:
        raise ValueError("weekly_kwh muss 52 Einträge haben.")
    hours_per_week = hours_per_year // 52
    profile: list[float] = []
    for week_kwh in weekly_kwh:
        kw = week_kwh / max(1, hours_per_week)
        profile.extend([round(kw, 6)] * hours_per_week)
    while len(profile) < hours_per_year:
        profile.append(profile[-1] if profile else 0.0)
    return profile[:hours_per_year]
