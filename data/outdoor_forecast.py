"""Stündliche Außentemperatur-Prognose (Open-Meteo)."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone as _timezone
from typing import Iterator, Optional
from zoneinfo import ZoneInfo

import requests

import config
from runtime_store.cycle_duration_stats import (
    EVENT_WEATHER_FETCH,
    record_event as record_cycle_event,
)
from runtime_store.planning_clock import cache_entry_fresh, planning_now

logger = logging.getLogger(__name__)

_UTC = _timezone.utc

HOURLY_TEMP_VAR = "temperature_2m"
HOURLY_TILTED_VAR = "global_tilted_irradiance"

_CACHE: dict[tuple[float, float, int], tuple[datetime, list[tuple[datetime, float]]]] = {}
# (lat, lon, forecast_days, tilt, azimuth) → (fetched_at, hourly W/m²)
_TILTED_CACHE: dict[
    tuple[float, float, int, int, int], tuple[datetime, list[tuple[datetime, float]]]
] = {}
_CACHE_TTL = timedelta(minutes=30)
# Longest series fetched while a cycle is open (recorder). None outside a cycle.
_capture: ContextVar[dict | None] = ContextVar("earnie_outdoor_forecast_capture", default=None)
# Recorded series while replaying. ``_REPLAY_MISSING`` forbids a live fetch.
_serve: ContextVar[dict | None] = ContextVar("earnie_outdoor_forecast_serve", default=None)
_REPLAY_MISSING: dict = {"missing": True}
_capture_token = None
_OPEN_METEO_MAX_FORECAST_DAYS = 16
_OPEN_METEO_MIN_FORECAST_DAYS = 2


def _required_forecast_days(start: datetime, horizon: int) -> int:
    """Kalendertage für Open-Meteo ab heute, damit start..start+horizon abgedeckt ist."""
    if horizon < 1:
        raise ValueError("horizon muss mindestens 1 sein")
    end = start + timedelta(hours=horizon - 1)
    # Real clock: Open-Meteo counts forecast_days from the request's real today
    # (an early-started cycle before midnight must still ask for enough days).
    today = datetime.now().date()
    days_ahead = (end.date() - today).days + 1
    return max(
        _OPEN_METEO_MIN_FORECAST_DAYS,
        min(_OPEN_METEO_MAX_FORECAST_DAYS, days_ahead),
    )


def _fetch_open_meteo_hourly(
    lat: float,
    lon: float,
    *,
    forecast_days: int,
) -> list[tuple[datetime, float]]:
    return _fetch_open_meteo_hourly_vars(
        lat, lon, forecast_days=forecast_days, hourly_vars=(HOURLY_TEMP_VAR,)
    )[HOURLY_TEMP_VAR]


def _fetch_open_meteo_hourly_vars(
    lat: float,
    lon: float,
    *,
    forecast_days: int,
    hourly_vars: tuple[str, ...],
    extra_params: dict | None = None,
) -> dict[str, list[tuple[datetime, float]]]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(hourly_vars),
        **utc_forecast_params(forecast_days),
    }
    if extra_params:
        params.update(extra_params)
    payload = _open_meteo_payload(url, params)
    return _parse_open_meteo_hourly(
        payload, hourly_vars, timezone=config.get_planning_timezone()
    )


def utc_forecast_params(forecast_days: int) -> dict:
    """Open-Meteo forecast window requested in UTC.

    With a zone name (or ``auto``) Open-Meteo applies ONE fixed UTC offset to the whole
    response (the offset valid on the request day), so hours on the other side of a clock
    change are 1 h off. UTC stamps are converted per timestamp instead. The first local
    hours of a day belong to the previous UTC day and the last ones may fall behind the
    UTC-day count, hence one past day and one extra forecast day.
    """
    return {
        "timezone": "UTC",
        "past_days": 1,
        "forecast_days": min(_OPEN_METEO_MAX_FORECAST_DAYS, forecast_days + 1),
    }


def _open_meteo_payload(url: str, params: dict):
    """Open-Meteo JSON via the shadow-aware transport (replay in shadow, record in prod)."""
    from runtime_store.shadow.feed import url_hash
    from runtime_store.shadow.mode import is_shadow_mode
    from runtime_store.shadow.replay import replay_ext_payload
    from runtime_store.shadow.transport import ext_get, safe_record

    # Hash path+params only (no secrets).
    param_key = "&".join(f"{k}={params[k]}" for k in sorted(params))
    feed_key = f"ext:outdoor:{url_hash(url + '?' + param_key)}"

    def _replay() -> dict | None:
        payload = replay_ext_payload(feed_key)
        return payload if isinstance(payload, dict) else None

    def _live() -> dict | object:
        # Family B: Shadow fallback must not record; Prod records.
        if is_shadow_mode():
            response = requests.get(
                url, params=params, timeout=config.get_global_timeout()
            )
            payload = response.json()
            response.raise_for_status()
            return payload
        try:
            response = requests.get(
                url, params=params, timeout=config.get_global_timeout()
            )
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            if response.status_code >= 400:
                safe_record(
                    feed_key,
                    ok=False,
                    status=int(response.status_code),
                    payload=payload,
                    error=f"HTTP {response.status_code}",
                )
                response.raise_for_status()
            safe_record(
                feed_key, ok=True, payload=payload, status=int(response.status_code)
            )
            return payload
        except Exception as exc:
            safe_record(feed_key, ok=False, error=str(exc))
            raise

    return ext_get(replay=_replay, live=_live, allow_live_fallback=True)


def _utc_stamps_to_local_naive(times: list, timezone: str) -> list[datetime]:
    """UTC stamps of a ``timezone=UTC`` response -> naive local wall-clock of ``timezone``."""
    tz = ZoneInfo(timezone)
    return [
        datetime.fromisoformat(str(ts_text))
        .replace(tzinfo=_UTC)
        .astimezone(tz)
        .replace(tzinfo=None)
        for ts_text in times
    ]


def _parse_open_meteo_hourly(
    payload, hourly_vars: tuple[str, ...], *, timezone: str
) -> dict[str, list[tuple[datetime, float]]]:
    """Hourly series of a UTC response as local wall-clock of ``timezone``.

    The repeated hour of the autumn clock change is averaged; the skipped spring hour is absent.
    """
    hourly = payload.get("hourly", {}) if isinstance(payload, dict) else {}
    times = hourly.get("time", [])
    parsed_times = _utc_stamps_to_local_naive(times, timezone)
    out: dict[str, list[tuple[datetime, float]]] = {}
    for var in hourly_vars:
        values = hourly.get(var, [])
        if not times or not values or len(times) != len(values) or None in values:
            raise ValueError(f"Open-Meteo: hourly {var} unvollständig")
        grouped: dict[datetime, list[float]] = {}
        for ts, value in zip(parsed_times, values):
            grouped.setdefault(ts, []).append(float(value))
        out[var] = [(ts, sum(vals) / len(vals)) for ts, vals in grouped.items()]
    return out


def _is_skipped_local_hour(moment: datetime) -> bool:
    """True for a wall-clock time that does not exist (spring clock change gap)."""
    tz = ZoneInfo(config.get_planning_timezone())
    round_trip = moment.replace(tzinfo=tz).astimezone(_UTC).astimezone(tz)
    return round_trip.replace(tzinfo=None) != moment


def _map_to_horizon(
    hourly: list[tuple[datetime, float]],
    start: datetime,
    horizon: int,
) -> list[float]:
    by_hour = {dt.replace(minute=0, second=0, microsecond=0): temp for dt, temp in hourly}
    vector: list[float] = []
    for offset in range(horizon):
        key = (start + timedelta(hours=offset)).replace(minute=0, second=0, microsecond=0)
        if key not in by_hour and _is_skipped_local_hour(key):
            # The clock jumps over this hour: the planning grid is hour-indexed wall clock,
            # so the position carries the value of the hour the clock lands on.
            key += timedelta(hours=1)
        if key not in by_hour:
            raise ValueError(f"Open-Meteo: keine Temperatur für {key.isoformat()}")
        vector.append(round(by_hour[key], 3))
    return vector


def outdoor_temps_for_slots(
    slot_datetimes: list[datetime],
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[float]:
    """Outdoor °C for each planning slot (hourly Open-Meteo held onto QH)."""
    if not slot_datetimes:
        return []
    start = min(slot_datetimes).replace(minute=0, second=0, microsecond=0)
    end = max(slot_datetimes)
    wall_hours = max(1, int((end - start).total_seconds() // 3600) + 1)
    hourly_vals = get_hourly_outdoor_forecast_c(
        horizon=wall_hours,
        latitude=latitude,
        longitude=longitude,
        start=start,
    )
    by_hour = {
        (start + timedelta(hours=i)).replace(minute=0, second=0, microsecond=0): hourly_vals[i]
        for i in range(len(hourly_vals))
    }
    out: list[float] = []
    for slot in slot_datetimes:
        key = slot.replace(minute=0, second=0, microsecond=0)
        if key not in by_hour:
            raise ValueError(f"Open-Meteo: keine Temperatur für {key.isoformat()}")
        out.append(by_hour[key])
    return out


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
    start_dt = (start or planning_now()).replace(minute=0, second=0, microsecond=0)
    forecast_days = _required_forecast_days(start_dt, horizon)

    cache_key = (round(lat, 4), round(lon, 4), forecast_days)
    cached = _CACHE.get(cache_key)
    now = datetime.now()
    if cached and cache_entry_fresh(
        cached[0].timestamp(), _CACHE_TTL.total_seconds(), now_epoch=now.timestamp()
    ):
        hourly = cached[1]
    else:
        record_cycle_event(EVENT_WEATHER_FETCH)
        hourly = _fetch_open_meteo_hourly(lat, lon, forecast_days=forecast_days)
        _CACHE[cache_key] = (now, hourly)

    try:
        return _map_to_horizon(hourly, start_dt, horizon)
    except ValueError as exc:
        logger.warning("Open-Meteo-Mapping fehlgeschlagen: %s", exc)
        raise


def get_hourly_tilted_irradiance_forecast_wm2(
    *,
    horizon: int,
    tilt_deg: float,
    azimuth_deg: float,
    latitude: float,
    longitude: float,
    start: datetime | None = None,
) -> list[float]:
    """Hourly global tilted irradiance (W/m²) for one surface over ``horizon`` hours.

    Same Open-Meteo conventions as the archive path (``tilt``/``azimuth`` rounded
    to whole degrees, azimuth 0° = south). One request also carries
    ``temperature_2m`` and seeds the outdoor-temperature cache for the location.
    """
    if horizon < 1:
        raise ValueError("horizon muss mindestens 1 sein")
    lat = float(latitude)
    lon = float(longitude)
    tilt = int(round(float(tilt_deg)))
    azimuth = int(round(float(azimuth_deg)))
    start_dt = (start or planning_now()).replace(minute=0, second=0, microsecond=0)
    forecast_days = _required_forecast_days(start_dt, horizon)

    cache_key = (round(lat, 4), round(lon, 4), forecast_days, tilt, azimuth)
    cached = _TILTED_CACHE.get(cache_key)
    now = datetime.now()
    if cached and cache_entry_fresh(
        cached[0].timestamp(), _CACHE_TTL.total_seconds(), now_epoch=now.timestamp()
    ):
        hourly = cached[1]
    else:
        record_cycle_event(EVENT_WEATHER_FETCH)
        series = _fetch_open_meteo_hourly_vars(
            lat,
            lon,
            forecast_days=forecast_days,
            hourly_vars=(HOURLY_TEMP_VAR, HOURLY_TILTED_VAR),
            extra_params={"tilt": tilt, "azimuth": azimuth},
        )
        hourly = series[HOURLY_TILTED_VAR]
        _TILTED_CACHE[cache_key] = (now, hourly)
        _CACHE[(round(lat, 4), round(lon, 4), forecast_days)] = (now, series[HOURLY_TEMP_VAR])
    return _map_to_horizon(hourly, start_dt, horizon)


def open_forecast_capture() -> dict:
    """Start storing the longest outdoor series fetched until :func:`close_forecast_capture`."""
    global _capture_token
    bucket: dict = {}
    _capture_token = _capture.set(bucket)
    return bucket


def close_forecast_capture() -> dict | None:
    """Stop capture and return the bucket, or None when capture was not open."""
    global _capture_token
    if _capture_token is None:
        return None
    bucket = _capture.get()
    _capture.reset(_capture_token)
    _capture_token = None
    return bucket


@contextmanager
def replay_outdoor_forecast(recorded: dict | None) -> Iterator[None]:
    """Serve ``recorded`` during replay. ``None`` fails on the next forecast read.

    Callers that replay cycles recorded before ``outdoor_forecast`` existed should
    not enter this context at all, so the live fetch / ambient fallback stays.
    """
    token = _serve.set(recorded if recorded else _REPLAY_MISSING)
    try:
        yield
    finally:
        _serve.reset(token)


def _note_captured_forecast(series: list[float], source: str) -> None:
    bucket = _capture.get()
    if bucket is None:
        return
    previous = bucket.get("values_c")
    if isinstance(previous, list) and len(previous) > len(series):
        return
    bucket["values_c"] = [float(value) for value in series]
    bucket["source"] = source


def _fetch_outdoor_forecast_or_fallback(
    *,
    horizon: int,
    fallback_ambient_c: float,
    start: datetime | None,
) -> tuple[list[float], str]:
    try:
        return get_hourly_outdoor_forecast_c(horizon=horizon, start=start), "open_meteo"
    except Exception as exc:
        logger.warning(
            "Außentemperatur-Prognose fehlgeschlagen (%s) – konstante Fallback-Temperatur %.2f °C",
            exc,
            fallback_ambient_c,
        )
        return [round(float(fallback_ambient_c), 3)] * horizon, "fallback_constant"


def _series_from_recording(recorded: dict, horizon: int) -> tuple[list[float], str]:
    if recorded.get("missing"):
        raise ValueError(
            "entry recorded start_state.outdoor_forecast as empty (no forecast "
            "was read during the live cycle); replay must not fetch one"
        )
    values = recorded.get("values_c")
    source = recorded.get("source")
    if not isinstance(values, list) or not values or not isinstance(source, str):
        raise ValueError(
            "start_state.outdoor_forecast must be {values_c: [float, ...], source: str}"
        )
    if horizon > len(values):
        raise ValueError(
            f"recorded outdoor forecast has {len(values)} hours, replay asked for {horizon}"
        )
    return [float(value) for value in values[:horizon]], source


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
    recorded = _serve.get()
    if recorded is not None:
        series, source = _series_from_recording(recorded, horizon)
    else:
        series, source = _fetch_outdoor_forecast_or_fallback(
            horizon=horizon,
            fallback_ambient_c=float(fallback_ambient_c),
            start=start,
        )
        _note_captured_forecast(series, source)
    return series, source
