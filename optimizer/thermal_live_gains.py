"""Live gains of the house RC over the ThermalHorizon (SUSI P2).

Same sources as the year model (``optimizer.house_gains``), taken from what Live knows before
the MILP runs:

- Grundlast: the Live consumption forecast ``expected_p_act`` of the matrix (hourly mean) ×
  ``baseload_internal_gain_factor``. Without a matrix (observability snapshot) the flat
  Grundlast of the year model.
- other consumers: their modeled kW per hour (schedules) × ``internal_gain_factor``.
- windows: Open-Meteo forecast irradiance on the four vertical surfaces; when the forecast
  fails, the last full archive year at the same day / hour with a warning (same rule as the
  collector, ThermalHorizon P3).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from house_config.house_gains import (
    INTERNAL_GAIN_FACTOR_KEY,
    INTERNAL_GAINS_KEY,
    SOLAR_GAINS_KEY,
    WINDOW_DIRECTIONS,
    solar_gains_active,
)
from optimizer.thermal_live_solar import (
    SOLAR_SOURCE_ARCHIVE_FALLBACK,
    SOLAR_SOURCE_FORECAST,
    SOLAR_SOURCE_NONE,
)

logger = logging.getLogger("optimizer.thermal_live_store")


def matrix_hourly_kw(matrix: list, key: str, horizon: int) -> list[float]:
    """Hourly mean of a matrix kW column (wall-clock hour from the horizon start)."""
    from optimizer.charging_context import matrix_slot_datetime

    sums = [0.0] * horizon
    counts = [0] * horizon
    if not matrix:
        return sums
    start = matrix_slot_datetime(matrix, 0)
    for index, row in enumerate(matrix):
        offset = int((matrix_slot_datetime(matrix, index) - start).total_seconds() // 3600)
        if 0 <= offset < horizon:
            sums[offset] += float(row.get(key, 0.0) or 0.0)
            counts[offset] += 1
    return [s / c if c else 0.0 for s, c in zip(sums, counts)]


def _consumer_gain_kw(internal: dict[str, Any], start: datetime, horizon: int) -> list[float]:
    from data.consumption_profiles import modeled_consumer_kw_at_datetime

    out = [0.0] * horizon
    for consumer in internal.get("consumers") or []:
        factor = float(consumer.get(INTERNAL_GAIN_FACTOR_KEY, 0.0) or 0.0)
        if factor <= 0.0:
            continue
        for hour in range(horizon):
            slot = start + timedelta(hours=hour)
            out[hour] += factor * float(modeled_consumer_kw_at_datetime(consumer, slot))
    return out


def _flat_baseload_kw(thermal: dict[str, Any], consumer: dict, house_profile: dict) -> float:
    """Grundlast kW of the year model (no matrix): annual − others − own heating electric."""
    from optimizer.house_gains import baseload_gain_kw, other_consumers_annual_kwh
    from optimizer.thermal_live_house import _thermal_with_nominal
    from optimizer.thermal_parameters import house_thermal_parameters

    internal = thermal.get(INTERNAL_GAINS_KEY) or {}
    factor = float(internal.get("baseload_factor", 0.0) or 0.0)
    if factor <= 0.0:
        return 0.0
    own = house_thermal_parameters(
        _thermal_with_nominal(thermal, consumer), house_profile=house_profile
    ).annual_electric_kwh
    gain = baseload_gain_kw(
        internal,
        others_kwh=other_consumers_annual_kwh(internal),
        own_electric_kwh=float(own),
    )
    return gain / factor


def _window_wm2_forecast(
    profile: dict, direction: str, start: datetime, horizon: int
) -> tuple[list[float], str]:
    from data.outdoor_forecast import get_hourly_tilted_irradiance_forecast_wm2
    from optimizer.house_gains import window_surface

    surface = window_surface(direction)
    try:
        values = get_hourly_tilted_irradiance_forecast_wm2(
            horizon=horizon,
            tilt_deg=surface.tilt_deg,
            azimuth_deg=surface.azimuth_deg,
            latitude=float(profile["latitude"]),
            longitude=float(profile["longitude"]),
            start=start,
        )
        return [max(0.0, float(v or 0.0)) for v in values], SOLAR_SOURCE_FORECAST
    except Exception as exc:  # noqa: BLE001 — same documented fallback as the collector
        logger.warning(
            "Fenster-Einstrahlungsprognose (%s) fehlgeschlagen (%s) – nutze Vorjahreswerte "
            "(Open-Meteo-Archiv) für die solaren Gewinne.",
            direction,
            exc,
        )
        return _archive_window_wm2(profile, surface, start, horizon), SOLAR_SOURCE_ARCHIVE_FALLBACK


def _archive_window_wm2(profile: dict, surface, start: datetime, horizon: int) -> list[float]:
    from data.modeled_climate import ModeledClimateContext
    from data.open_meteo_solar_archive import last_full_archive_year

    climate = ModeledClimateContext.for_house_profile(profile, kwp=0.0)
    year = last_full_archive_year()
    bundle = climate._bundle_for_calendar_year(year)
    series = bundle.tilted_wm2.get(surface)
    if series is None:
        from data.open_meteo_solar_archive import build_open_meteo_climate_bundle_for_year
        from data.modeled_climate import _planning_timezone_for_thermal

        bundle = build_open_meteo_climate_bundle_for_year(
            year,
            lat=float(profile["latitude"]),
            lon=float(profile["longitude"]),
            timezone=_planning_timezone_for_thermal({}, profile),
            surfaces=[surface],
        )
    out: list[float] = []
    for offset in range(horizon):
        slot = start + timedelta(hours=offset)
        try:
            archive_slot = slot.replace(year=year)
        except ValueError:
            archive_slot = slot.replace(year=year, day=28)
        value = bundle._irradiance_wm2_at(surface, archive_slot)
        out.append(max(0.0, float(value or 0.0)))
    return out


def live_solar_gain_kw(
    thermal: dict[str, Any], house_profile: dict | None, *, start: datetime, horizon: int
) -> tuple[list[float], str]:
    """Window gain kW per horizon hour plus its source (``none`` when solar gains are off)."""
    if not solar_gains_active(thermal):
        return [0.0] * horizon, SOLAR_SOURCE_NONE
    from optimizer.thermal_live_solar import _profile_with_geo

    profile = _profile_with_geo(house_profile)
    block = thermal[SOLAR_GAINS_KEY]
    factor = float(block["g_value"]) * float(block["frame_shading_factor"]) / 1000.0
    out = [0.0] * horizon
    sources: set[str] = set()
    for direction in WINDOW_DIRECTIONS:
        area = float(block["window_area_m2"][direction])
        if area <= 0.0:
            continue
        wm2, source = _window_wm2_forecast(profile, direction, start, horizon)
        sources.add(source)
        for hour in range(horizon):
            out[hour] += area * factor * wm2[hour]
    source = (
        SOLAR_SOURCE_ARCHIVE_FALLBACK if SOLAR_SOURCE_ARCHIVE_FALLBACK in sources
        else SOLAR_SOURCE_FORECAST
    )
    return out, source


def live_gain_kw_by_hour(
    consumer: dict,
    house_profile: dict,
    *,
    start: datetime,
    horizon: int,
    baseload_kw_by_hour: list[float] | None,
) -> tuple[list[float], str]:
    """Solar + internal gains (kW) per Live horizon hour and the window irradiance source.

    ``baseload_kw_by_hour``: Grundlast forecast of the matrix; None = flat Grundlast of the
    year model (no matrix at hand).
    """
    thermal = consumer.get("thermal") or consumer
    start_hour = start.replace(minute=0, second=0, microsecond=0)
    solar, source = live_solar_gain_kw(thermal, house_profile, start=start_hour, horizon=horizon)
    internal = thermal.get(INTERNAL_GAINS_KEY)
    if not internal:
        return solar, source
    factor = float(internal.get("baseload_factor", 0.0) or 0.0)
    if baseload_kw_by_hour is None:
        flat = _flat_baseload_kw(thermal, consumer, house_profile)
        baseload = [flat] * horizon
    else:
        baseload = list(baseload_kw_by_hour) + [0.0] * max(0, horizon - len(baseload_kw_by_hour))
    consumers = _consumer_gain_kw(internal, start_hour, horizon)
    gains = [
        solar[h] + factor * float(baseload[h]) + consumers[h] for h in range(horizon)
    ]
    return gains, source
