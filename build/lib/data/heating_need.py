"""Thermischer Jahresbedarf (WP-Strom) — extrahiert aus config/prognosis-heating-need.py."""
from __future__ import annotations

import json
import math
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

_BUILDING_KWH_M2 = {1: 15.0, 2: 45.0, 3: 80.0, 4: 130.0}
_JAZ = {"luft": 3.5, "erde": 4.3}
_SOLAR_THERMAL_EFFICIENCY = 0.40
SOLAR_THERMAL_EFFICIENCY = _SOLAR_THERMAL_EFFICIENCY
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


def _daily_hdd_values(
    daily_temps: list[float],
    target_temp_c: float,
    heating_limit_c: float,
) -> list[float]:
    return [
        max(0.0, target_temp_c - t) if t < heating_limit_c else 0.0
        for t in daily_temps
    ]


def daily_heating_factors(
    daily_temps: list[float],
    target_temp_c: float,
    heating_limit_c: float,
) -> list[float]:
    if not daily_temps or len(daily_temps) < 364:
        return [1.0 / 365] * 365
    hdd = _daily_hdd_values(daily_temps, target_temp_c, heating_limit_c)
    total = sum(hdd)
    if total == 0:
        return [1.0 / len(hdd)] * len(hdd)
    return [h / total for h in hdd]


def weekly_heating_factors(
    daily_temps: list[float],
    target_temp_c: float,
    heating_limit_c: float,
) -> list[float]:
    if not daily_temps or len(daily_temps) < 364:
        return [1.0 / 52] * 52
    hdd = _daily_hdd_values(daily_temps, target_temp_c, heating_limit_c)
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


def daily_solar_thermal_kwh(
    radiation_mj_year: list[float],
    day_idx: int,
    area_m2: float,
    lat: float,
    tilt: float,
    azimuth: float,
) -> float:
    """Thermischer Solarertrag eines Tages (kWh_th) mit Tilt und Azimuth."""
    if not radiation_mj_year or area_m2 <= 0.0:
        return 0.0
    day_of_year = day_idx + 1
    if day_of_year > len(radiation_mj_year):
        return 0.0
    horizontal_kwh = radiation_mj_year[day_of_year - 1] / 3.6
    r_factor = daily_transposition_factor(lat, day_of_year, tilt, azimuth)
    return horizontal_kwh * r_factor * area_m2 * _SOLAR_THERMAL_EFFICIENCY


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
        week_yield += daily_solar_thermal_kwh(
            radiation_mj_year,
            (week_idx * 7) + day_offset,
            area_m2,
            lat,
            tilt,
            azimuth,
        )
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


def _net_electric_kwh(
    heat_kwh: float,
    warm_water_kwh: float,
    solar_kwh: float,
    jaz: float,
) -> float:
    gross_heat = heat_kwh + warm_water_kwh
    net_heat = max(0.0, gross_heat - solar_kwh)
    return net_heat / jaz


def _daily_solar_kwh_by_date_from_hourly_wm2(
    hourly_wm2: pd.Series,
    area_m2: float,
    *,
    eta: float = _SOLAR_THERMAL_EFFICIENCY,
) -> dict[date, float]:
    from data.open_meteo_solar_archive import irradiance_wm2_to_thermal_kwh

    if hourly_wm2.empty:
        raise ValueError("hourly_collector_wm2 ist leer.")
    by_date: dict[date, float] = {}
    for ts, wm2 in hourly_wm2.items():
        day = pd.Timestamp(ts).date()
        by_date[day] = by_date.get(day, 0.0) + irradiance_wm2_to_thermal_kwh(
            wm2,
            area_m2,
            eta=eta,
        )
    return by_date


def _daily_temperatures_from_hourly(
    hourly_temperature_c: pd.Series,
) -> tuple[list[date], list[float]]:
    if hourly_temperature_c.empty:
        raise ValueError("hourly_temperature_c ist leer.")
    grouped = hourly_temperature_c.groupby(hourly_temperature_c.index.date).mean()
    dates = sorted(grouped.index)
    return dates, [float(grouped[day]) for day in dates]


def _resolve_climate_series(
    *,
    latitude: float,
    longitude: float,
    daily_temps: list[float] | None,
    daily_radiation_mj: list[float] | None,
    solar_thermal_area_m2: float,
    hourly_temperature_c: pd.Series | None = None,
    hourly_collector_wm2: pd.Series | None = None,
) -> tuple[list[float], list[float] | None, list[date] | None]:
    area_m2 = float(solar_thermal_area_m2)
    calendar_dates: list[date] | None = None

    if hourly_temperature_c is not None:
        calendar_dates, daily_temps = _daily_temperatures_from_hourly(hourly_temperature_c)

    if daily_temps is None or (
        area_m2 > 0.0
        and daily_radiation_mj is None
        and hourly_collector_wm2 is None
    ):
        fixture_temps, fixture_radiation = load_climate_daily(
            lat=latitude,
            lon=longitude,
        )
        if daily_temps is None:
            daily_temps = fixture_temps
        if area_m2 > 0.0 and daily_radiation_mj is None and hourly_collector_wm2 is None:
            daily_radiation_mj = fixture_radiation

    if area_m2 > 0.0 and hourly_collector_wm2 is not None:
        daily_radiation_mj = None
    elif area_m2 > 0.0 and not daily_radiation_mj:
        raise ValueError(
            "solar_thermal_area_m2 > 0 erfordert shortwave_radiation_sum "
            "oder hourly_collector_wm2 in den Klimadaten."
        )
    return daily_temps, daily_radiation_mj, calendar_dates


def daily_electric_kwh(
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
    hourly_temperature_c: pd.Series | None = None,
    hourly_collector_wm2: pd.Series | None = None,
    hwb_kwh_m2: float | None = None,
    solar_thermal_area_m2: float = 0.0,
    solar_thermal_tilt_deg: float = 18.0,
    solar_thermal_azimuth_deg: float = 0.0,
) -> list[float]:
    """Elektrischer WP-Bedarf pro Kalendertag (kWh)."""
    area_m2 = float(solar_thermal_area_m2)
    daily_temps, daily_radiation_mj, calendar_dates = _resolve_climate_series(
        latitude=latitude,
        longitude=longitude,
        daily_temps=daily_temps,
        daily_radiation_mj=daily_radiation_mj,
        solar_thermal_area_m2=area_m2,
        hourly_temperature_c=hourly_temperature_c,
        hourly_collector_wm2=hourly_collector_wm2,
    )
    solar_by_date: dict[date, float] | None = None
    if area_m2 > 0.0 and hourly_collector_wm2 is not None:
        solar_by_date = _daily_solar_kwh_by_date_from_hourly_wm2(
            hourly_collector_wm2,
            area_m2,
        )
    annual_heat = living_area_m2 * specific_heating_kwh_m2(
        building_class,
        hwb_kwh_m2=hwb_kwh_m2,
    )
    factors = daily_heating_factors(daily_temps, target_temp_c, heating_limit_c)
    ww_day = warm_water_kwh_week(persons) / 7.0
    jaz = heat_pump_jaz(heat_pump_type)
    daily: list[float] = []
    for day_idx, factor in enumerate(factors):
        heat_day = annual_heat * factor
        solar_day = 0.0
        if solar_by_date is not None and calendar_dates is not None:
            if day_idx < len(calendar_dates):
                solar_day = solar_by_date.get(calendar_dates[day_idx], 0.0)
        elif area_m2 > 0.0 and daily_radiation_mj:
            solar_day = daily_solar_thermal_kwh(
                daily_radiation_mj,
                day_idx,
                area_m2,
                latitude,
                float(solar_thermal_tilt_deg),
                float(solar_thermal_azimuth_deg),
            )
        daily.append(
            round(_net_electric_kwh(heat_day, ww_day, solar_day, jaz), 3)
        )
    return daily


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
    hourly_temperature_c: pd.Series | None = None,
    hourly_collector_wm2: pd.Series | None = None,
    hwb_kwh_m2: float | None = None,
    solar_thermal_area_m2: float = 0.0,
    solar_thermal_tilt_deg: float = 18.0,
    solar_thermal_azimuth_deg: float = 0.0,
) -> list[float]:
    """Elektrischer WP-Bedarf pro Kalenderwoche (kWh)."""
    daily = daily_electric_kwh(
        living_area_m2=living_area_m2,
        building_class=building_class,
        heat_pump_type=heat_pump_type,
        persons=persons,
        latitude=latitude,
        longitude=longitude,
        target_temp_c=target_temp_c,
        heating_limit_c=heating_limit_c,
        daily_temps=daily_temps,
        daily_radiation_mj=daily_radiation_mj,
        hourly_temperature_c=hourly_temperature_c,
        hourly_collector_wm2=hourly_collector_wm2,
        hwb_kwh_m2=hwb_kwh_m2,
        solar_thermal_area_m2=solar_thermal_area_m2,
        solar_thermal_tilt_deg=solar_thermal_tilt_deg,
        solar_thermal_azimuth_deg=solar_thermal_azimuth_deg,
    )
    weekly: list[float] = []
    for week_idx in range(52):
        start = week_idx * 7
        end = start + 7
        weekly.append(round(sum(daily[start:end]), 3))
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


_THERMAL_PWM_MIN_ON_H = 1
_THERMAL_PWM_MAX_ON_H = 4


def _pwm_pulse_durations(
    on_hours_total: float,
    *,
    min_on_h: int = _THERMAL_PWM_MIN_ON_H,
    max_on_h: int = _THERMAL_PWM_MAX_ON_H,
) -> list[float]:
    """Teilt benötigte Laufzeit in Pulse à 1–4 h (letzter Puls ggf. kürzer)."""
    if on_hours_total <= 0.0:
        return []
    pulses: list[float] = []
    remaining = on_hours_total
    while remaining > 1e-6:
        if remaining <= max_on_h:
            pulses.append(remaining)
            break
        pulses.append(float(max_on_h))
        remaining -= max_on_h
    return pulses


def _pwm_pulse_start_hours(
    day_index: int,
    pulse_lengths: list[int],
) -> list[int]:
    """Startstunden für Pulse — gleichmäßig über den Tag verteilt."""
    pulse_count = len(pulse_lengths)
    if pulse_count == 0:
        return []
    total_on = sum(pulse_lengths)
    free_slots = max(0, 24 - total_on)
    if pulse_count == 1:
        max_start = max(0, 24 - pulse_lengths[0])
        return [day_index % (max_start + 1)]
    gap = free_slots // (pulse_count + 1)
    gap = max(1, gap)
    offset = day_index % gap
    starts: list[int] = []
    cursor = gap + offset
    for length in pulse_lengths:
        starts.append(min(cursor, 24 - length))
        cursor += length + gap
    return starts


def _apply_pwm_pulse(
    day_hours: list[float],
    start_hour: int,
    duration_h: float,
    nominal: float,
) -> None:
    remaining_kwh = duration_h * nominal
    hour = start_hour
    while remaining_kwh > 1e-6 and hour < 24:
        slot_kw = min(nominal, remaining_kwh)
        day_hours[hour] = round(slot_kw, 6)
        remaining_kwh -= slot_kw
        hour += 1


def _thermal_pwm_day_hourly(
    day_index: int,
    day_kwh: float,
    nominal: float,
    *,
    min_on_h: int = _THERMAL_PWM_MIN_ON_H,
    max_on_h: int = _THERMAL_PWM_MAX_ON_H,
) -> list[float]:
    """Tägliches PWM-Profil: volle Nennleistung oder 0 kW, Pulse 1–4 h."""
    day_hours = [0.0] * 24
    if day_kwh <= 0.0 or nominal <= 0.0:
        return day_hours
    pulse_durations = _pwm_pulse_durations(
        day_kwh / nominal,
        min_on_h=min_on_h,
        max_on_h=max_on_h,
    )
    pulse_lengths = [
        max(1, int(math.ceil(duration)))
        if duration >= min_on_h
        else 1
        for duration in pulse_durations
    ]
    start_hours = _pwm_pulse_start_hours(day_index, pulse_lengths)
    for start, duration in zip(start_hours, pulse_durations):
        _apply_pwm_pulse(day_hours, start, duration, nominal)
    return day_hours


def thermal_daily_pwm_hourly_profile(
    daily_kwh: list[float],
    *,
    nominal_power_kw: float,
    hours_per_year: int = 8760,
    min_on_h: int = _THERMAL_PWM_MIN_ON_H,
    max_on_h: int = _THERMAL_PWM_MAX_ON_H,
) -> list[float]:
    """
    Thermisches Profil: tägliches PWM mit 1–4 h Einschaltzyklen bei Nennleistung.
    Tages-kWh werden auf mehrere Pulse pro Tag verteilt (nicht wöchentlich gebündelt).
    """
    if not daily_kwh:
        raise ValueError("daily_kwh darf nicht leer sein.")
    nominal = float(nominal_power_kw)
    if nominal <= 0.0:
        hours_per_day = 24
        flat_kw = sum(daily_kwh) / max(1, len(daily_kwh) * hours_per_day)
        return [round(flat_kw, 6)] * hours_per_year
    profile: list[float] = []
    for day_index, day_kwh in enumerate(daily_kwh):
        profile.extend(
            _thermal_pwm_day_hourly(
                day_index,
                float(day_kwh),
                nominal,
                min_on_h=min_on_h,
                max_on_h=max_on_h,
            )
        )
    while len(profile) < hours_per_year:
        profile.append(0.0)
    return profile[:hours_per_year]


def thermal_on_off_hourly_profile(
    weekly_kwh: list[float],
    *,
    nominal_power_kw: float,
    hours_per_year: int = 8760,
) -> list[float]:
    """
    Thermisches Profil: volle Nennleistung oder 0 kW (kein flacher Wochenmittelwert).
    Wochen-kWh werden in volle und ggf. eine partielle Stunde aufgeteilt.
    """
    if len(weekly_kwh) != 52:
        raise ValueError("weekly_kwh muss 52 Einträge haben.")
    nominal = float(nominal_power_kw)
    if nominal <= 0.0:
        return hourly_profile_for_year(weekly_kwh, hours_per_year=hours_per_year)
    hours_per_week = hours_per_year // 52
    profile: list[float] = []
    for week_kwh in weekly_kwh:
        remaining = float(week_kwh)
        week_hours: list[float] = []
        for _ in range(hours_per_week):
            if remaining >= nominal:
                week_hours.append(round(nominal, 6))
                remaining -= nominal
            elif remaining > 0.0:
                week_hours.append(round(remaining, 6))
                remaining = 0.0
            else:
                week_hours.append(0.0)
        profile.extend(week_hours)
    while len(profile) < hours_per_year:
        profile.append(0.0)
    return profile[:hours_per_year]
