"""Thermischer Jahresbedarf (WP-Strom) — extrahiert aus config/prognosis-heating-need.py."""
from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

_BUILDING_KWH_M2 = {1: 15.0, 2: 45.0, 3: 80.0, 4: 130.0}
_JAZ = {"luft": 3.5, "erde": 4.3}
_CLIMATE_CACHE = Path("data/cache/heating_climate_default.json")


def specific_heating_kwh_m2(building_class: int) -> float:
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


def fetch_climate(lat: float, lon: float, year: int = 2025) -> dict:
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
        f"&start_date={year}-01-01&end_date={year}-12-31"
        f"&daily=temperature_2m_mean&timezone=auto"
    )
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode())


def load_climate_fixture() -> list[float]:
    if not _CLIMATE_CACHE.is_file():
        raise FileNotFoundError(
            f"Klimadaten-Fixture fehlt: {_CLIMATE_CACHE}. "
            "Für Tests data/cache/heating_climate_default.json anlegen."
        )
    with _CLIMATE_CACHE.open(encoding="utf-8") as handle:
        data = json.load(handle)
    temps = data.get("daily", {}).get("temperature_2m_mean", [])
    if len(temps) < 364:
        raise ValueError("heating_climate_default.json: temperature_2m_mean unvollständig.")
    return [float(t) for t in temps]


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
) -> list[float]:
    """Elektrischer WP-Bedarf pro Kalenderwoche (kWh)."""
    if daily_temps is None:
        daily_temps = load_climate_fixture()
    annual_heat = living_area_m2 * specific_heating_kwh_m2(building_class)
    factors = weekly_heating_factors(daily_temps, target_temp_c, heating_limit_c)
    ww_week = warm_water_kwh_week(persons)
    jaz = heat_pump_jaz(heat_pump_type)
    weekly: list[float] = []
    for factor in factors:
        heat_week = annual_heat * factor + ww_week
        weekly.append(round(heat_week / jaz, 3))
    return weekly


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
