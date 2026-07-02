"""Stündliche Außentemperatur-Prognose (Open-Meteo)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

_CACHE: dict[tuple[float, float], tuple[datetime, list[float]]] = {}
_CACHE_TTL = timedelta(minutes=30)


def _fetch_open_meteo_hourly(lat: float, lon: float) -> list[tuple[datetime, float]]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "forecast_days": 2,
        "timezone": "auto",
    }
    response = requests.get(url, params=params, timeout=config.get_global_timeout())
    response.raise_for_status()
    payload = response.json()
    times = payload.get("hourly", {}).get("time", [])
    temps = payload.get("hourly", {}).get("temperature_2m", [])
    if not times or not temps or len(times) != len(temps):
        raise ValueError("Open-Meteo: hourly temperature_2m unvollständig")
    parsed: list[tuple[datetime, float]] = []
    for ts_text, temp in zip(times, temps):
        parsed.append((datetime.fromisoformat(str(ts_text)), float(temp)))
    return parsed


def _map_to_horizon(
    hourly: list[tuple[datetime, float]],
    start: datetime,
    horizon: int,
) -> list[float]:
    by_hour = {dt.replace(minute=0, second=0, microsecond=0): temp for dt, temp in hourly}
    vector: list[float] = []
    for offset in range(horizon):
        key = (start + timedelta(hours=offset)).replace(minute=0, second=0, microsecond=0)
        if key not in by_hour:
            raise ValueError(f"Open-Meteo: keine Temperatur für {key.isoformat()}")
        vector.append(round(by_hour[key], 3))
    return vector


def get_hourly_outdoor_forecast_c(
    *,
    horizon: int = 24,
    latitude: float | None = None,
    longitude: float | None = None,
    start: datetime | None = None,
) -> list[float]:
    """
    Stündliche Außentemperatur in °C für die nächsten `horizon` Stunden ab `start`.
    """
    if horizon < 1:
        raise ValueError("horizon muss mindestens 1 sein")
    lat = float(latitude if latitude is not None else config.get("LATITUDE", cast=float))
    lon = float(longitude if longitude is not None else config.get("LONGITUDE", cast=float))
    start_dt = (start or datetime.now()).replace(minute=0, second=0, microsecond=0)

    cache_key = (round(lat, 4), round(lon, 4))
    cached = _CACHE.get(cache_key)
    now = datetime.now()
    if cached and now - cached[0] < _CACHE_TTL:
        hourly = cached[1]
    else:
        hourly = _fetch_open_meteo_hourly(lat, lon)
        _CACHE[cache_key] = (now, hourly)

    try:
        return _map_to_horizon(hourly, start_dt, horizon)
    except ValueError as exc:
        logger.warning("Open-Meteo-Mapping fehlgeschlagen: %s", exc)
        raise


def get_outdoor_forecast_with_fallback(
    *,
    horizon: int = 24,
    fallback_ambient_c: Optional[float] = None,
    start: datetime | None = None,
) -> tuple[list[float], str]:
    """Prognose mit Quellenlabel; bei Fehler konstante Fallback-Temperatur."""
    if fallback_ambient_c is None:
        raise ValueError(
            "fallback_ambient_c fehlt – für Open-Meteo-Fallback eine gemessene Außentemperatur angeben."
        )
    try:
        return get_hourly_outdoor_forecast_c(horizon=horizon, start=start), "open_meteo"
    except Exception as exc:
        logger.warning(
            "Außentemperatur-Prognose fehlgeschlagen (%s) – konstante Fallback-Temperatur %.2f °C",
            exc,
            fallback_ambient_c,
        )
        return [round(float(fallback_ambient_c), 3)] * horizon, "fallback_constant"
