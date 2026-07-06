"""EU-Wetter- und Erzeugungsfeatures für Preisprognose-Training (Spec: price-forecast-renewables)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

import config

ENERGY_CHARTS_BASE = "https://api.energy-charts.info"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
AT_BIDDING_ZONE = "AT"
API_RETRY_ATTEMPTS = 5
API_RETRY_BASE_SECONDS = 2.0
API_PAUSE_SECONDS = 0.75
WIND_PRODUCTION_NAMES = frozenset({"Wind onshore", "Wind offshore"})
SOLAR_PRODUCTION_NAME = "Solar"
LOAD_PRODUCTION_NAME = "Load"
RESIDUAL_LOAD_PRODUCTION_NAME = "Residual load"

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


def fetch_eu_weather_hourly(start: date, end: date) -> pd.DataFrame:
    """Kapazitätsgewichteter EU-Mittelwert Wind und Einstrahlung."""
    wind_sum = None
    solar_sum = None
    wind_weight_total = sum(p.wind_weight for p in WEATHER_GRID)
    solar_weight_total = sum(p.solar_weight for p in WEATHER_GRID)
    for point in WEATHER_GRID:
        frames: list[pd.DataFrame] = []
        for chunk_start, chunk_end in month_ranges(start, end):
            frames.append(_fetch_open_meteo_archive_month(point, chunk_start, chunk_end))
        point_frame = pd.concat(frames)
        point_frame = _dedupe_hourly_mean(point_frame)
        weighted = pd.DataFrame(index=point_frame.index)
        weighted["wind"] = point_frame["wind_speed_kmh"] * point.wind_weight
        weighted["solar"] = point_frame["shortwave_radiation_wm2"] * point.solar_weight
        if wind_sum is None:
            wind_sum = weighted["wind"]
            solar_sum = weighted["solar"]
        else:
            wind_sum = wind_sum.add(weighted["wind"], fill_value=0.0)
            solar_sum = solar_sum.add(weighted["solar"], fill_value=0.0)
    if wind_sum is None or solar_sum is None:
        raise ValueError("EU-Wetterdaten konnten nicht geladen werden.")
    result = pd.DataFrame(index=wind_sum.index)
    result["eu_wind_speed_kmh"] = wind_sum / wind_weight_total
    result["eu_shortwave_radiation_wm2"] = solar_sum / solar_weight_total
    mask = (result.index.date >= start) & (result.index.date < end)
    return result.loc[mask].sort_index()


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
