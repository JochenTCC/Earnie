"""Live collector solar heat input for the store plan (split from thermal_live_store)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from optimizer.thermal_live_ref import live
from runtime_store.planning_clock import planning_now

# Same logger name as before the split (callers/tests filter on it).
logger = logging.getLogger("optimizer.thermal_live_store")

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
    start_dt = (start or planning_now()).replace(minute=0, second=0, microsecond=0)
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
            live._archive_year_collector_solar_kw(profile, surface, area_m2, start_dt, horizon),
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
