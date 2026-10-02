"""EU-Wetter- und Erzeugungsfeatures für Preisprognose-Training (Spec: price-forecast-renewables)."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

import config
from data.eu_forecast_disk_cache import (
    DEFAULT_TTL_SEC,
    KIND_POWER,
    KIND_WEATHER,
    load_frame,
    mark_warming,
    refresh_status_from_disk,
    save_frame,
)

POWER_FORECAST_FETCH_WORKERS = 4

ENERGY_CHARTS_BASE = "https://api.energy-charts.info"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
AT_BIDDING_ZONE = "AT"
API_RETRY_ATTEMPTS = 5
API_RETRY_BASE_SECONDS = 2.0
API_PAUSE_SECONDS = 0.75
WIND_PRODUCTION_NAMES = frozenset({"Wind onshore", "Wind offshore"})
SOLAR_PRODUCTION_NAME = "Solar"
LOAD_PRODUCTION_NAME = "Load"
RESIDUAL_LOAD_PRODUCTION_NAME = "Residual load"
POWER_FORECAST_PRODUCTION_TYPES: tuple[str, ...] = (
    "solar",
    "wind_onshore",
    "wind_offshore",
)
POWER_FORECAST_TYPES: tuple[str, ...] = ("day-ahead", "current")
POWER_FORECAST_CACHE_TTL_SEC = 45 * 60

logger = logging.getLogger(__name__)
_power_forecast_cache: dict[tuple[str, str, str], tuple[float, pd.DataFrame]] = {}
_weather_forecast_cache: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}
_power_refresh_lock = threading.Lock()
_power_refresh_inflight: set[tuple[str, str]] = set()
_weather_refresh_lock = threading.Lock()
_weather_refresh_inflight: set[tuple[str, str]] = set()

GENERATION_COUNTRIES: tuple[str, ...] = (
    "de",
    "at",
    "fr",
    "nl",
    "be",
    "pl",
    "es",
    "it",
    "dk",
    "se",
    "cz",
    "pt",
)


@dataclass(frozen=True)
class WeatherGridPoint:
    """Kapazitätsnaher Gitterpunkt für EU-Wetter-Mittelung."""

    name: str
    latitude: float
    longitude: float
    wind_weight: float
    solar_weight: float


WEATHER_GRID: tuple[WeatherGridPoint, ...] = (
    WeatherGridPoint("de", 51.0, 10.5, 0.30, 0.28),
    WeatherGridPoint("fr", 46.5, 2.5, 0.10, 0.12),
    WeatherGridPoint("es", 40.0, -3.5, 0.08, 0.15),
    WeatherGridPoint("it", 42.5, 12.5, 0.05, 0.10),
    WeatherGridPoint("nl", 52.2, 5.5, 0.12, 0.05),
    WeatherGridPoint("pl", 52.0, 19.5, 0.08, 0.06),
    WeatherGridPoint("at", 47.5, 14.0, 0.02, 0.04),
    WeatherGridPoint("be", 50.5, 4.5, 0.03, 0.03),
    WeatherGridPoint("dk", 56.0, 10.0, 0.10, 0.02),
    WeatherGridPoint("se", 62.0, 15.0, 0.08, 0.03),
    WeatherGridPoint("cz", 49.8, 15.5, 0.02, 0.04),
    WeatherGridPoint("pt", 39.5, -8.0, 0.02, 0.08),
)


def planning_timezone() -> ZoneInfo:
    return ZoneInfo(config.get_planning_timezone())


def normalize_hour_slot(moment: datetime) -> datetime:
    tz = planning_timezone()
    if moment.tzinfo is None:
        aligned = moment.replace(tzinfo=tz)
    else:
        aligned = moment.astimezone(tz)
    return aligned.replace(minute=0, second=0, microsecond=0)


def month_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """Teilt [start, end) in Monatsblöcke für API-Abrufe."""
    if end <= start:
        raise ValueError("end muss nach start liegen.")
    ranges: list[tuple[date, date]] = []
    cursor = start.replace(day=1)
    while cursor < end:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        chunk_end = min(next_month, end)
        chunk_start = max(cursor, start)
        if chunk_start < chunk_end:
            ranges.append((chunk_start, chunk_end))
        cursor = next_month
    return ranges


def _http_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(API_RETRY_ATTEMPTS):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=config.get_global_timeout(),
            )
            if response.status_code == 429:
                wait = API_RETRY_BASE_SECONDS * (2 ** attempt)
                time.sleep(wait)
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"Unerwartete API-Antwort von {url}")
            time.sleep(API_PAUSE_SECONDS)
            return payload
        except requests.HTTPError as exc:
            last_error = exc
            if exc.response is not None and exc.response.status_code == 429:
                time.sleep(API_RETRY_BASE_SECONDS * (2 ** attempt))
                continue
            raise
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(API_RETRY_BASE_SECONDS * (2 ** attempt))
    raise RuntimeError(f"API-Abruf fehlgeschlagen ({url}): {last_error}")


def _dedupe_hourly_mean(frame: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Mittelt doppelte Stunden-Slots."""
    if frame.index.has_duplicates:
        return frame.groupby(level=0).mean()
    return frame


def _public_power_hourly(payload: dict[str, Any]) -> pd.DataFrame:
    seconds = payload.get("unix_seconds") or []
    if not seconds:
        raise ValueError("Energy-Charts public_power: unix_seconds fehlt.")
    tz = planning_timezone()
    index = pd.DatetimeIndex(
        [datetime.fromtimestamp(int(ts), tz=tz) for ts in seconds],
        name="slot_datetime",
    )
    series = {
        "wind_mw": pd.Series(0.0, index=index),
        "solar_mw": pd.Series(0.0, index=index),
        "load_mw": pd.Series(0.0, index=index),
        "residual_load_mw": pd.Series(0.0, index=index),
    }
    for entry in payload.get("production_types") or []:
        name = entry.get("name")
        values = entry.get("data") or []
        if len(values) != len(index):
            continue
        value_series = pd.Series(values, index=index)
        if name in WIND_PRODUCTION_NAMES:
            series["wind_mw"] = series["wind_mw"].add(value_series, fill_value=0.0)
        elif name == SOLAR_PRODUCTION_NAME:
            series["solar_mw"] = series["solar_mw"].add(value_series, fill_value=0.0)
        elif name == LOAD_PRODUCTION_NAME:
            series["load_mw"] = series["load_mw"].add(value_series, fill_value=0.0)
        elif name == RESIDUAL_LOAD_PRODUCTION_NAME:
            series["residual_load_mw"] = series["residual_load_mw"].add(
                value_series, fill_value=0.0
            )
    return pd.DataFrame(series).resample("h").mean()


def _renewable_series_from_public_power(payload: dict[str, Any]) -> pd.DataFrame:
    """Rückwärtskompatibel: nur Wind/Solar."""
    hourly = _public_power_hourly(payload)
    return hourly[["wind_mw", "solar_mw"]]


def fetch_country_power_hourly(
    country: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Stündliche Wind/Solar/Last/Residuallast je Land (Energy-Charts)."""
    frames: list[pd.DataFrame] = []
    for chunk_start, chunk_end in month_ranges(start, end):
        payload = _http_get_json(
            f"{ENERGY_CHARTS_BASE}/public_power",
            {
                "country": country,
                "start": chunk_start.isoformat(),
                "end": (chunk_end - timedelta(days=1)).isoformat()
                if chunk_end > chunk_start
                else chunk_start.isoformat(),
            },
        )
        frames.append(_public_power_hourly(payload))
    if not frames:
        raise ValueError(f"Keine Erzeugungsdaten für {country}.")
    merged = pd.concat(frames)
    merged = _dedupe_hourly_mean(merged)
    merged.index = merged.index.map(normalize_hour_slot)
    return merged.sort_index()


def fetch_country_renewables_hourly(
    country: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Nur Wind/Solar (Kompatibilitäts-Wrapper)."""
    return fetch_country_power_hourly(country, start, end)[["wind_mw", "solar_mw"]]


def fetch_eu_power_hourly(start: date, end: date) -> pd.DataFrame:
    """Summierte EU-Wind, Solar, Last und Residuallast (MW) je Stunde."""
    total: pd.DataFrame | None = None
    for country in GENERATION_COUNTRIES:
        country_frame = fetch_country_power_hourly(country, start, end)
        country_frame = country_frame.rename(
            columns={col: f"{col}_{country}" for col in country_frame.columns}
        )
        if total is None:
            total = country_frame
        else:
            total = total.join(country_frame, how="outer")
    if total is None:
        raise ValueError("EU-Leistungsdaten konnten nicht geladen werden.")
    result = pd.DataFrame(index=total.index)
    for base, eu_name in (
        ("wind_mw", "eu_wind_mw"),
        ("solar_mw", "eu_solar_mw"),
        ("load_mw", "eu_load_mw"),
        ("residual_load_mw", "eu_residual_load_mw"),
    ):
        cols = [c for c in total.columns if c.startswith(f"{base}_")]
        result[eu_name] = total[cols].sum(axis=1, min_count=1)
    mask = (result.index.date >= start) & (result.index.date < end)
    return result.loc[mask].sort_index()


def fetch_eu_renewables_hourly(start: date, end: date) -> pd.DataFrame:
    """Summierte EU-Wind- und Solar-Erzeugung (MW) je Stunde."""
    power = fetch_eu_power_hourly(start, end)
    return power[["eu_wind_mw", "eu_solar_mw"]]


def _public_power_forecast_hourly(payload: dict[str, Any]) -> pd.Series:
    """Parse one Energy-Charts public_power_forecast payload → hourly MW series."""
    seconds = payload.get("unix_seconds") or []
    values = payload.get("forecast_values") or []
    if not seconds:
        raise ValueError("Energy-Charts public_power_forecast: unix_seconds fehlt.")
    if len(values) != len(seconds):
        raise ValueError(
            "Energy-Charts public_power_forecast: forecast_values Länge != unix_seconds."
        )
    tz = planning_timezone()
    index = pd.DatetimeIndex(
        [datetime.fromtimestamp(int(ts), tz=tz) for ts in seconds],
        name="slot_datetime",
    )
    cleaned = [float(v) if v is not None else float("nan") for v in values]
    series = pd.Series(cleaned, index=index, dtype=float)
    return series.resample("h").mean()


def _fetch_country_production_forecast(
    country: str,
    production_type: str,
    start: date,
    end: date,
) -> pd.Series | None:
    """One country/production_type; try day-ahead then current. None if empty."""
    end_inclusive = (end - timedelta(days=1)).isoformat() if end > start else start.isoformat()
    for forecast_type in POWER_FORECAST_TYPES:
        try:
            payload = _http_get_json(
                f"{ENERGY_CHARTS_BASE}/public_power_forecast",
                {
                    "country": country,
                    "production_type": production_type,
                    "forecast_type": forecast_type,
                    "start": start.isoformat(),
                    "end": end_inclusive,
                },
            )
            series = _public_power_forecast_hourly(payload)
            if series.empty or series.isna().all():
                continue
            series = _dedupe_hourly_mean(series)
            series.index = series.index.map(normalize_hour_slot)
            return series.sort_index()
        except (OSError, ValueError, requests.HTTPError, RuntimeError) as exc:
            logger.debug(
                "public_power_forecast %s/%s/%s: %s",
                country,
                production_type,
                forecast_type,
                exc,
            )
            continue
    return None


def fetch_country_power_forecast_hourly(
    country: str,
    start: date,
    end: date,
) -> pd.DataFrame | None:
    """Stündliche Wind/Solar-Prognose je Land (Energy-Charts public_power_forecast)."""
    wind = pd.Series(dtype=float)
    solar = pd.Series(dtype=float)
    got_any = False
    for production_type in POWER_FORECAST_PRODUCTION_TYPES:
        series = _fetch_country_production_forecast(
            country, production_type, start, end
        )
        if series is None:
            logger.warning(
                "Preisprognose-Research: keine public_power_forecast für %s/%s.",
                country,
                production_type,
            )
            continue
        got_any = True
        if production_type == "solar":
            solar = solar.add(series, fill_value=0.0) if not solar.empty else series
        else:
            wind = wind.add(series, fill_value=0.0) if not wind.empty else series
    if not got_any:
        return None
    index = wind.index.union(solar.index)
    frame = pd.DataFrame(index=index)
    frame["wind_mw"] = wind.reindex(index)
    frame["solar_mw"] = solar.reindex(index)
    return frame.sort_index()


def _aggregate_country_power_forecasts(
    country_frames: list[tuple[str, pd.DataFrame]],
    start: date,
    end: date,
) -> pd.DataFrame:
    total: pd.DataFrame | None = None
    countries_used = 0
    for country, country_frame in country_frames:
        if country_frame is None or country_frame.empty:
            continue
        countries_used += 1
        renamed = country_frame.rename(
            columns={col: f"{col}_{country}" for col in country_frame.columns}
        )
        if total is None:
            total = renamed
        else:
            total = total.join(renamed, how="outer")
    if total is None or countries_used == 0:
        raise ValueError(
            "EU public_power_forecast: keine Länderdaten im Zeitraum "
            f"{start}..{end}."
        )
    if countries_used < len(GENERATION_COUNTRIES):
        logger.warning(
            "Preisprognose-Research: EU-Leistungsprognose nur für %d/%d Länder.",
            countries_used,
            len(GENERATION_COUNTRIES),
        )
    result = pd.DataFrame(index=total.index)
    for base, eu_name in (("wind_mw", "eu_wind_mw"), ("solar_mw", "eu_solar_mw")):
        cols = [c for c in total.columns if c.startswith(f"{base}_")]
        result[eu_name] = total[cols].sum(axis=1, min_count=1)
    result["eu_load_mw"] = 0.0
    result["eu_residual_load_mw"] = 0.0
    mask = (result.index.date >= start) & (result.index.date < end)
    result = result.loc[mask].sort_index()
    if result.empty or result[["eu_wind_mw", "eu_solar_mw"]].isna().all().all():
        raise ValueError("EU public_power_forecast: leerer Wind/Solar-Frame.")
    return result


def _fetch_eu_power_forecast_network(start: date, end: date) -> pd.DataFrame:
    """HTTP fan-out for all GENERATION_COUNTRIES (parallel)."""
    country_frames: list[tuple[str, pd.DataFrame]] = []
    with ThreadPoolExecutor(max_workers=POWER_FORECAST_FETCH_WORKERS) as pool:
        futures = {
            pool.submit(fetch_country_power_forecast_hourly, country, start, end): country
            for country in GENERATION_COUNTRIES
        }
        for future in as_completed(futures):
            country = futures[future]
            try:
                frame = future.result()
            except Exception as exc:  # noqa: BLE001 — per-country isolation
                logger.warning(
                    "Preisprognose-Research: public_power_forecast %s fehlgeschlagen (%s).",
                    country,
                    type(exc).__name__,
                )
                frame = None
            if frame is not None and not frame.empty:
                country_frames.append((country, frame))
    return _aggregate_country_power_forecasts(country_frames, start, end)


def _store_power_forecast_caches(
    start: date, end: date, result: pd.DataFrame
) -> None:
    cache_key = (start.isoformat(), end.isoformat(), "eu_power_forecast")
    now = time.time()
    _power_forecast_cache[cache_key] = (now, result)
    try:
        save_frame(KIND_POWER, start, end, result)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("EU-Leistungsprognose Disk-Cache Schreibfehler: %s", exc)


def schedule_power_forecast_refresh(start: date, end: date) -> bool:
    """Start background HTTP refresh once per range. Returns True if scheduled."""
    key = (start.isoformat(), end.isoformat())
    with _power_refresh_lock:
        if key in _power_refresh_inflight:
            return False
        _power_refresh_inflight.add(key)

    def _worker() -> None:
        t0 = time.time()
        try:
            logger.info(
                "Preisprognose-Research: Lade public_power_forecast %s..%s (Hintergrund)…",
                start.isoformat(),
                end.isoformat(),
            )
            mark_warming(start, end)
            result = _fetch_eu_power_forecast_network(start, end)
            _store_power_forecast_caches(start, end, result)
            refresh_status_from_disk(start, end)
            logger.info(
                "Preisprognose-Research: public_power_forecast fertig in %.1fs.",
                time.time() - t0,
            )
        except Exception as exc:  # noqa: BLE001 — background must not kill process
            logger.warning(
                "Preisprognose-Research: public_power_forecast Hintergrund fehlgeschlagen (%s).",
                type(exc).__name__,
            )
            refresh_status_from_disk(start, end, error=str(exc))
        finally:
            with _power_refresh_lock:
                _power_refresh_inflight.discard(key)

    threading.Thread(
        target=_worker, name="eu-power-forecast-cache", daemon=True
    ).start()
    return True


def fetch_eu_power_forecast_hourly(
    start: date,
    end: date,
    *,
    blocking: bool = True,
    allow_stale: bool = True,
) -> pd.DataFrame | None:
    """Summierte EU-Wind/Solar-Prognose (MW); partial country coverage allowed.

    Research-only live path (``eu_power_live_source=energy_charts_forecast``).

    ``blocking=True`` (scripts/tests): sync HTTP on miss.
    ``blocking=False``: memory → disk (fresh or stale) → else schedule refresh and
    return ``None`` (caller falls back to mirror).
    """
    cache_key = (start.isoformat(), end.isoformat(), "eu_power_forecast")
    cached = _power_forecast_cache.get(cache_key)
    if cached is not None:
        stored_at, frame = cached
        age = time.time() - stored_at
        if age <= POWER_FORECAST_CACHE_TTL_SEC:
            return frame.copy()
        if allow_stale:
            schedule_power_forecast_refresh(start, end)
            return frame.copy()
        _power_forecast_cache.pop(cache_key, None)

    disk_frame, _age, is_fresh = load_frame(
        KIND_POWER, start, end, ttl_sec=POWER_FORECAST_CACHE_TTL_SEC
    )
    if disk_frame is not None:
        _power_forecast_cache[cache_key] = (
            time.time() - (_age or 0.0),
            disk_frame,
        )
        if is_fresh:
            return disk_frame.copy()
        if allow_stale:
            schedule_power_forecast_refresh(start, end)
            return disk_frame.copy()

    if not blocking:
        schedule_power_forecast_refresh(start, end)
        return None

    result = _fetch_eu_power_forecast_network(start, end)
    _store_power_forecast_caches(start, end, result)
    refresh_status_from_disk(start, end)
    return result.copy()


def fetch_at_day_ahead_hourly(start: date, end: date) -> pd.Series:
    """AT Day-Ahead EPEX in Cent/kWh (stündlich)."""
    frames: list[pd.Series] = []
    for chunk_start, chunk_end in month_ranges(start, end):
        payload = _http_get_json(
            f"{ENERGY_CHARTS_BASE}/price",
            {
                "bzn": AT_BIDDING_ZONE,
                "start": chunk_start.isoformat(),
                "end": (chunk_end - timedelta(days=1)).isoformat()
                if chunk_end > chunk_start
                else chunk_start.isoformat(),
            },
        )
        seconds = payload.get("unix_seconds") or []
        prices = payload.get("price") or []
        if not seconds or not prices:
            raise ValueError("Energy-Charts price: keine AT-Daten.")
        tz = planning_timezone()
        index = pd.DatetimeIndex(
            [normalize_hour_slot(datetime.fromtimestamp(int(ts), tz=tz)) for ts in seconds]
        )
        series = pd.Series(
            [float(p) / 10.0 for p in prices],
            index=index,
            name="price_epex_cent_kwh",
        )
        frames.append(series)
    merged = pd.concat(frames)
    merged = _dedupe_hourly_mean(merged)
    mask = (merged.index.date >= start) & (merged.index.date < end)
    return merged.loc[mask].sort_index()


def _fetch_open_meteo_archive_month(
    point: WeatherGridPoint,
    start: date,
    end: date,
) -> pd.DataFrame:
    payload = _http_get_json(
        OPEN_METEO_ARCHIVE,
        {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "start_date": start.isoformat(),
            "end_date": (end - timedelta(days=1)).isoformat(),
            "hourly": "wind_speed_10m,shortwave_radiation",
            "timezone": config.get_planning_timezone(),
        },
    )
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    wind = hourly.get("wind_speed_10m") or []
    radiation = hourly.get("shortwave_radiation") or []
    if not times or len(times) != len(wind) or len(times) != len(radiation):
        raise ValueError(f"Open-Meteo unvollständig für {point.name}.")
    tz = planning_timezone()
    index = pd.DatetimeIndex(
        [normalize_hour_slot(datetime.fromisoformat(str(ts)).replace(tzinfo=tz)) for ts in times]
    )
    return pd.DataFrame(
        {
            "wind_speed_kmh": wind,
            "shortwave_radiation_wm2": radiation,
        },
        index=index,
    )


def _weighted_eu_weather_from_points(
    point_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Kapazitätsgewichteter EU-Mittelwert aus pro-Gitterpunkt-Frames."""
    wind_sum = None
    solar_sum = None
    wind_weight_total = sum(p.wind_weight for p in WEATHER_GRID)
    solar_weight_total = sum(p.solar_weight for p in WEATHER_GRID)
    for point in WEATHER_GRID:
        point_frame = point_frames.get(point.name)
        if point_frame is None or point_frame.empty:
            raise ValueError(f"EU-Wetterdaten fehlen für Gitterpunkt {point.name}.")
        point_frame = _dedupe_hourly_mean(point_frame)
        weighted_wind = point_frame["wind_speed_kmh"] * point.wind_weight
        weighted_solar = point_frame["shortwave_radiation_wm2"] * point.solar_weight
        if wind_sum is None:
            wind_sum = weighted_wind
            solar_sum = weighted_solar
        else:
            wind_sum = wind_sum.add(weighted_wind, fill_value=0.0)
            solar_sum = solar_sum.add(weighted_solar, fill_value=0.0)
    if wind_sum is None or solar_sum is None:
        raise ValueError("EU-Wetterdaten konnten nicht geladen werden.")
    result = pd.DataFrame(index=wind_sum.index)
    result["eu_wind_speed_kmh"] = wind_sum / wind_weight_total
    result["eu_shortwave_radiation_wm2"] = solar_sum / solar_weight_total
    return result.sort_index()


def fetch_eu_weather_hourly(start: date, end: date) -> pd.DataFrame:
    """Kapazitätsgewichteter EU-Mittelwert Wind und Einstrahlung (Archiv)."""
    point_frames: dict[str, pd.DataFrame] = {}
    for point in WEATHER_GRID:
        frames: list[pd.DataFrame] = []
        for chunk_start, chunk_end in month_ranges(start, end):
            frames.append(_fetch_open_meteo_archive_month(point, chunk_start, chunk_end))
        point_frames[point.name] = pd.concat(frames)
    result = _weighted_eu_weather_from_points(point_frames)
    mask = (result.index.date >= start) & (result.index.date < end)
    return result.loc[mask].sort_index()


def _forecast_days_for_range(start: date, end: date) -> int:
    """Open-Meteo forecast_days covering [start, end)."""
    tz = planning_timezone()
    today = datetime.now(tz).date()
    last_needed = end - timedelta(days=1)
    days_ahead = (last_needed - today).days + 1
    return max(1, min(16, days_ahead))


def _hourly_frame_from_open_meteo_payload(payload: dict[str, Any]) -> pd.DataFrame:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    wind = hourly.get("wind_speed_10m") or []
    radiation = hourly.get("shortwave_radiation") or []
    if not times or len(times) != len(wind) or len(times) != len(radiation):
        raise ValueError("Open-Meteo Forecast unvollständig.")
    tz = planning_timezone()
    index = pd.DatetimeIndex(
        [
            normalize_hour_slot(datetime.fromisoformat(str(ts)).replace(tzinfo=tz))
            for ts in times
        ]
    )
    return pd.DataFrame(
        {
            "wind_speed_kmh": wind,
            "shortwave_radiation_wm2": radiation,
        },
        index=index,
    )


def _fetch_open_meteo_forecast_point(
    point: WeatherGridPoint,
    *,
    forecast_days: int,
) -> pd.DataFrame:
    payload = _http_get_json(
        OPEN_METEO_FORECAST,
        {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "hourly": "wind_speed_10m,shortwave_radiation",
            "forecast_days": forecast_days,
            "timezone": config.get_planning_timezone(),
        },
    )
    try:
        return _hourly_frame_from_open_meteo_payload(payload)
    except ValueError as exc:
        raise ValueError(f"{exc} ({point.name})") from exc


def _fetch_open_meteo_forecast_grid(*, forecast_days: int) -> dict[str, pd.DataFrame]:
    """One multi-location Open-Meteo call for the full EU weather grid."""
    lats = ",".join(str(p.latitude) for p in WEATHER_GRID)
    lons = ",".join(str(p.longitude) for p in WEATHER_GRID)
    raw = requests.get(
        OPEN_METEO_FORECAST,
        params={
            "latitude": lats,
            "longitude": lons,
            "hourly": "wind_speed_10m,shortwave_radiation",
            "forecast_days": forecast_days,
            "timezone": config.get_planning_timezone(),
        },
        timeout=config.get_global_timeout(),
    )
    raw.raise_for_status()
    payload = raw.json()
    locations = payload if isinstance(payload, list) else [payload]
    if len(locations) != len(WEATHER_GRID):
        raise ValueError(
            f"Open-Meteo Forecast: erwartet {len(WEATHER_GRID)} Standorte, "
            f"erhalten {len(locations)}."
        )
    return {
        point.name: _hourly_frame_from_open_meteo_payload(loc)
        for point, loc in zip(WEATHER_GRID, locations, strict=True)
    }


def _fetch_eu_weather_forecast_network(start: date, end: date) -> pd.DataFrame:
    forecast_days = _forecast_days_for_range(start, end)
    try:
        point_frames = _fetch_open_meteo_forecast_grid(forecast_days=forecast_days)
    except (OSError, ValueError, requests.HTTPError, requests.RequestException):
        point_frames = {
            point.name: _fetch_open_meteo_forecast_point(
                point, forecast_days=forecast_days
            )
            for point in WEATHER_GRID
        }
    result = _weighted_eu_weather_from_points(point_frames)
    mask = (result.index.date >= start) & (result.index.date < end)
    return result.loc[mask].sort_index()


def _store_weather_forecast_caches(
    start: date, end: date, result: pd.DataFrame
) -> None:
    cache_key = (start.isoformat(), end.isoformat())
    _weather_forecast_cache[cache_key] = (time.time(), result)
    try:
        save_frame(KIND_WEATHER, start, end, result)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("EU-Wetterprognose Disk-Cache Schreibfehler: %s", exc)


def schedule_weather_forecast_refresh(start: date, end: date) -> bool:
    key = (start.isoformat(), end.isoformat())
    with _weather_refresh_lock:
        if key in _weather_refresh_inflight:
            return False
        _weather_refresh_inflight.add(key)

    def _worker() -> None:
        t0 = time.time()
        try:
            logger.info(
                "Preisprognose: Lade EU-Wetterprognose %s..%s (Hintergrund)…",
                start.isoformat(),
                end.isoformat(),
            )
            result = _fetch_eu_weather_forecast_network(start, end)
            _store_weather_forecast_caches(start, end, result)
            refresh_status_from_disk(start, end)
            logger.info(
                "Preisprognose: EU-Wetterprognose fertig in %.1fs.",
                time.time() - t0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Preisprognose: EU-Wetterprognose Hintergrund fehlgeschlagen (%s).",
                type(exc).__name__,
            )
            refresh_status_from_disk(start, end, error=str(exc))
        finally:
            with _weather_refresh_lock:
                _weather_refresh_inflight.discard(key)

    threading.Thread(
        target=_worker, name="eu-weather-forecast-cache", daemon=True
    ).start()
    return True


def fetch_eu_weather_forecast_hourly(
    start: date,
    end: date,
    *,
    blocking: bool = True,
    allow_stale: bool = True,
) -> pd.DataFrame | None:
    """Kapazitätsgewichteter EU-Wetterprognose-Mittelwert (Open-Meteo Forecast)."""
    cache_key = (start.isoformat(), end.isoformat())
    cached = _weather_forecast_cache.get(cache_key)
    if cached is not None:
        stored_at, frame = cached
        age = time.time() - stored_at
        if age <= DEFAULT_TTL_SEC:
            return frame.copy()
        if allow_stale:
            schedule_weather_forecast_refresh(start, end)
            return frame.copy()
        _weather_forecast_cache.pop(cache_key, None)

    disk_frame, age, is_fresh = load_frame(
        KIND_WEATHER, start, end, ttl_sec=DEFAULT_TTL_SEC
    )
    if disk_frame is not None:
        _weather_forecast_cache[cache_key] = (
            time.time() - (age or 0.0),
            disk_frame,
        )
        if is_fresh:
            return disk_frame.copy()
        if allow_stale:
            schedule_weather_forecast_refresh(start, end)
            return disk_frame.copy()

    if not blocking:
        schedule_weather_forecast_refresh(start, end)
        return None

    result = _fetch_eu_weather_forecast_network(start, end)
    _store_weather_forecast_caches(start, end, result)
    refresh_status_from_disk(start, end)
    return result.copy()


def remap_power_by_hour_of_day(
    power: pd.DataFrame,
    target_hours: list[datetime],
) -> pd.DataFrame:
    """Map archive power rows onto target hours by clock hour (feature stand-in)."""
    if power.empty:
        raise ValueError("remap_power_by_hour_of_day: leeres power-DataFrame.")
    by_hour: dict[int, pd.Series] = {}
    for slot, row in power.iterrows():
        by_hour[int(slot.hour)] = row
    rows: list[pd.Series] = []
    index: list[datetime] = []
    for target in target_hours:
        hour = int(target.hour)
        if hour not in by_hour:
            raise ValueError(f"Keine Archiv-Leistungsdaten für Stunde {hour}.")
        rows.append(by_hour[hour])
        index.append(normalize_hour_slot(target))
    remapped = pd.DataFrame(rows, index=pd.DatetimeIndex(index, name=power.index.name))
    return _dedupe_hourly_mean(remapped).sort_index()


def _add_calendar_columns(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["hour"] = enriched.index.hour
    enriched["weekday"] = enriched.index.weekday
    enriched["month"] = enriched.index.month
    return enriched


def build_training_dataset(start: date, end: date) -> pd.DataFrame:
    """Stündliches Training-Dataset: AT-Preis + EU-Leistung + EU-Wetter."""
    prices = fetch_at_day_ahead_hourly(start, end)
    power = fetch_eu_power_hourly(start, end)
    weather = fetch_eu_weather_hourly(start, end)
    merged = pd.DataFrame({"price_epex_cent_kwh": prices})
    merged = merged.join(power, how="inner")
    merged = merged.join(weather, how="inner")
    merged = merged.dropna()
    if merged.empty:
        raise ValueError(
            f"Keine überlappenden Daten für {start} bis {end}. "
            "Zeitraum oder API-Verfügbarkeit prüfen."
        )
    return _add_calendar_columns(merged)


def enrich_dataset_with_eu_load(frame: pd.DataFrame) -> pd.DataFrame:
    """Ergänzt bestehendes Dataset um eu_load_mw und eu_residual_load_mw."""
    if frame.empty:
        raise ValueError("enrich_dataset_with_eu_load: leeres DataFrame.")
    start = frame.index.min().date()
    end = frame.index.max().date() + timedelta(days=1)
    power = fetch_eu_power_hourly(start, end)[["eu_load_mw", "eu_residual_load_mw"]]
    enriched = frame.join(power, how="left")
    missing = enriched[["eu_load_mw", "eu_residual_load_mw"]].isna().any(axis=1).sum()
    if missing:
        raise ValueError(
            f"Last/Residuallast fehlt für {missing} Stunden nach dem Join."
        )
    return enriched


def default_training_range() -> tuple[date, date]:
    """Rollierende 12 Monate bis gestern (Europe/Vienna)."""
    tz = planning_timezone()
    end = datetime.now(tz).date()
    start = end - timedelta(days=365)
    return start, end
