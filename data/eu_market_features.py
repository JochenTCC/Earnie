"""EU-Wetter- und Erzeugungsfeatures für Preisprognose-Training (Spec: price-forecast-renewables)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

import config
from data import opendata_session
from opendata import ApiUnreachableError, energy_charts, open_meteo  # noqa: F401  (ApiUnreachableError re-exported)

AT_BIDDING_ZONE = "AT"

logger = logging.getLogger(__name__)

class EuPowerIncompleteError(RuntimeError):
    """EU power data of at least one country could not be loaded.

    The OLS model was trained on the sum of all :data:`GENERATION_COUNTRIES`; a sum without
    one country would shift the features without any label on the forecast.
    """


EU_WEATHER_VARS = ("wind_speed_10m", "shortwave_radiation")
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
# Energy-Charts returns the local days of the requested country (``start``/``end`` as dates).
COUNTRY_TIMEZONES: dict[str, str] = {
    "de": "Europe/Berlin",
    "at": "Europe/Vienna",
    "fr": "Europe/Paris",
    "nl": "Europe/Amsterdam",
    "be": "Europe/Brussels",
    "pl": "Europe/Warsaw",
    "es": "Europe/Madrid",
    "it": "Europe/Rome",
    "dk": "Europe/Copenhagen",
    "se": "Europe/Stockholm",
    "cz": "Europe/Prague",
    "pt": "Europe/Lisbon",
}


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
        payload = energy_charts.public_power(
            opendata_session.session(),
            country=country,
            start=chunk_start,
            end=chunk_end - timedelta(days=1),
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


def _country_missing_message(country: str, start: date, end: date, exc: BaseException) -> str:
    return (
        f"EU-Leistungsdaten für {start.isoformat()} bis {end.isoformat()} unvollständig: "
        f"Land {country} fehlt ({type(exc).__name__}: {str(exc).split('?')[0][:180]})."
    )


def _is_country_without_data(exc: BaseException) -> bool:
    """Energy-Charts answered 404 ("no content available") for this country.

    Only this case may be stood in (:func:`fetch_eu_power_hourly_with_stand_in`): a rate
    limit (429) or a server error concerns the host, not the country.
    """
    response = getattr(exc, "response", None)
    return isinstance(exc, requests.HTTPError) and getattr(response, "status_code", None) == 404


def fetch_country_power_frames(
    start: date,
    end: date,
    *,
    tolerate_missing_countries: bool = False,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Hourly power per country of :data:`GENERATION_COUNTRIES` and the countries without data.

    A failed country raises :class:`EuPowerIncompleteError`; with
    ``tolerate_missing_countries`` a country Energy-Charts answers 404 for is returned in the
    second dict (country -> error summary) instead. An unreachable host
    (``ApiUnreachableError``) aborts at the first country.
    """
    frames: dict[str, pd.DataFrame] = {}
    missing: dict[str, str] = {}
    for country in GENERATION_COUNTRIES:
        try:
            frames[country] = fetch_country_power_hourly(country, start, end)
        except ApiUnreachableError:
            # The host does not answer: asking the other countries only repeats the wait.
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            message = _country_missing_message(country, start, end, exc)
            if tolerate_missing_countries and _is_country_without_data(exc):
                missing[country] = message
                continue
            raise EuPowerIncompleteError(message) from exc
    return frames, missing


def _join_country_frames(
    frames: dict[str, pd.DataFrame], start: date, end: date
) -> pd.DataFrame:
    total: pd.DataFrame | None = None
    for country, country_frame in frames.items():
        renamed = country_frame.rename(
            columns={col: f"{col}_{country}" for col in country_frame.columns}
        )
        total = renamed if total is None else total.join(renamed, how="outer")
    if total is None:
        raise EuPowerIncompleteError(
            f"EU-Leistungsdaten für {start.isoformat()} bis {end.isoformat()}: kein Land geladen."
        )
    mask = (total.index.date >= start) & (total.index.date < end)
    return total.loc[mask].sort_index()


def _missing_country_hours(total: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Per hour and country: True where the country has no value although it should.

    Energy-Charts returns the local days of each country, so a country in another time
    zone (``pt``) structurally lacks an edge hour of the planning window; such an hour is
    not expected and does not count. Inside the country's own days a missing hour counts
    (Denmark on 2026-11-04: data ended at 08:45 without any error).
    """
    missing = pd.DataFrame(False, index=total.index, columns=list(GENERATION_COUNTRIES))
    for country in GENERATION_COUNTRIES:
        tz = ZoneInfo(COUNTRY_TIMEZONES[country])
        first = datetime.combine(start, time.min, tzinfo=tz)
        stop = datetime.combine(end, time.min, tzinfo=tz)
        expected = (total.index >= first) & (total.index < stop)
        cols = [f"{base}_{country}" for base, _eu in EU_POWER_COLUMNS if f"{base}_{country}" in total]
        has_value = total[cols].notna().any(axis=1) if cols else pd.Series(False, index=total.index)
        missing[country] = expected & ~has_value.to_numpy()
    return missing


def _missing_hours_summary(missing: pd.DataFrame, country: str) -> str:
    hours = missing.index[missing[country]]
    return f"Land {country} ohne Werte für {len(hours)} Stunde(n) ab {hours[0]:%Y-%m-%d %H:%M}"


def _sum_eu_columns(total: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=total.index)
    for base, eu_name in EU_POWER_COLUMNS:
        cols = [c for c in total.columns if c.startswith(f"{base}_")]
        result[eu_name] = total[cols].sum(axis=1, min_count=1)
    return result


def fetch_eu_power_hourly(start: date, end: date) -> pd.DataFrame:
    """Summierte EU-Wind, Solar, Last und Residuallast (MW) je Stunde.

    Every country of :data:`GENERATION_COUNTRIES` must load, with a value in every hour of
    its own local days: a failed country or a gap raises :class:`EuPowerIncompleteError`
    naming it (archive, training). An unreachable host
    (``ApiUnreachableError``) aborts at the first country. The live forecast uses
    :func:`fetch_eu_power_hourly_with_stand_in`.
    """
    frames, _missing = fetch_country_power_frames(start, end)
    total = _join_country_frames(frames, start, end)
    missing = _missing_country_hours(total, start, end)
    gaps = [c for c in GENERATION_COUNTRIES if missing[c].any()]
    if gaps:
        raise EuPowerIncompleteError(
            f"EU-Leistungsdaten für {start.isoformat()} bis {end.isoformat()} unvollständig: "
            + "; ".join(_missing_hours_summary(missing, c) for c in gaps)
            + "."
        )
    return _sum_eu_columns(total)


# --- Country shares: stand-in for a country Energy-Charts has no data for -------------

EU_POWER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("wind_mw", "eu_wind_mw"),
    ("solar_mw", "eu_solar_mw"),
    ("load_mw", "eu_load_mw"),
    ("residual_load_mw", "eu_residual_load_mw"),
)
DEFAULT_COUNTRY_SHARES_PATH = Path("share/data/eu_power_country_shares.json")
COUNTRY_SHARES_VERSION = 1
# Largest share of an EU sum (per column, month and hour) the missing countries may have
# together; above it the stand-in would carry too much of the feature and the live
# forecast falls back to the mirror.
MAX_STAND_IN_SHARE = 0.15
# A (month, hour) bucket whose EU sum stays below this mean (MW) gets share 0: solar at
# night, where a ratio says nothing and the missing country adds nothing either.
_MIN_BUCKET_MEAN_MW = 1.0


@dataclass(frozen=True)
class CountryShares:
    """Mean share of each country in the EU sums, per column, month (1-12) and hour (0-23)."""

    range_start: str
    range_end: str
    # country -> base column (``wind_mw`` ...) -> 12 x 24 shares
    shares: dict[str, dict[str, list[list[float]]]]

    def share(self, country: str, base: str, month: int, hour: int) -> float:
        return self.shares[country][base][month - 1][hour]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": COUNTRY_SHARES_VERSION,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "countries": self.shares,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CountryShares:
        version = payload.get("version")
        if version != COUNTRY_SHARES_VERSION:
            raise ValueError(
                f"Länderanteile: Version {version!r} nicht unterstützt "
                f"(erwartet {COUNTRY_SHARES_VERSION})."
            )
        shares = payload["countries"]
        for country in GENERATION_COUNTRIES:
            if country not in shares:
                raise ValueError(f"Länderanteile: Land {country} fehlt.")
            for base, _eu in EU_POWER_COLUMNS:
                table = shares[country].get(base)
                if not isinstance(table, list) or len(table) != 12 or any(
                    len(row) != 24 for row in table
                ):
                    raise ValueError(
                        f"Länderanteile: {country}/{base} ist keine 12x24-Tabelle."
                    )
        return cls(
            range_start=str(payload["range_start"]),
            range_end=str(payload["range_end"]),
            shares=shares,
        )


def compute_country_shares(
    frames: dict[str, pd.DataFrame],
    *,
    range_start: date,
    range_end: date,
) -> CountryShares:
    """Shares per country from hourly per-country power (ratio of sums per month and hour).

    Only hours with data for every country count. Every month must be covered, else
    ``ValueError`` (a year of data is needed).
    """
    missing_countries = [c for c in GENERATION_COUNTRIES if c not in frames]
    if missing_countries:
        raise ValueError(f"Länderanteile: keine Daten für {', '.join(missing_countries)}.")
    shares: dict[str, dict[str, list[list[float]]]] = {c: {} for c in GENERATION_COUNTRIES}
    for base, _eu in EU_POWER_COLUMNS:
        table = pd.DataFrame({c: frames[c][base] for c in GENERATION_COUNTRIES}).dropna()
        months = sorted(set(table.index.month))
        if months != list(range(1, 13)):
            raise ValueError(
                f"Länderanteile: {base} deckt nur die Monate {months} ab (alle 12 nötig)."
            )
        table["_month"] = table.index.month
        table["_hour"] = table.index.hour
        grouped = table.groupby(["_month", "_hour"])
        sums = grouped[list(GENERATION_COUNTRIES)].sum()
        counts = grouped.size()
        total = sums.sum(axis=1)
        for country in GENERATION_COUNTRIES:
            rows: list[list[float]] = []
            for month in range(1, 13):
                row: list[float] = []
                for hour in range(24):
                    key = (month, hour)
                    if key not in total.index:
                        raise ValueError(
                            f"Länderanteile: {base} ohne Daten für Monat {month}, Stunde {hour}."
                        )
                    eu_sum = float(total.loc[key])
                    if abs(eu_sum) / int(counts.loc[key]) < _MIN_BUCKET_MEAN_MW:
                        row.append(0.0)
                    else:
                        row.append(round(float(sums.loc[key, country]) / eu_sum, 6))
                rows.append(row)
            shares[country][base] = rows
    return CountryShares(
        range_start=range_start.isoformat(),
        range_end=range_end.isoformat(),
        shares=shares,
    )


def save_country_shares(shares: CountryShares, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(shares.to_dict(), handle, indent=1, ensure_ascii=False)
        handle.write("\n")


def load_country_shares(path: Path = DEFAULT_COUNTRY_SHARES_PATH) -> CountryShares:
    with path.open(encoding="utf-8") as handle:
        return CountryShares.from_dict(json.load(handle))


def fetch_eu_power_hourly_with_stand_in(
    start: date,
    end: date,
    shares: CountryShares,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """EU sums like :func:`fetch_eu_power_hourly`; a country without data is stood in.

    Energy-Charts answering 404 for a country (it publishes no data for it, e.g. Denmark
    since 2026-11-04) does not drop the live forecast: the sum of the other countries is
    scaled by ``1 / (1 - share)`` with the missing countries' share from ``shares`` (per
    column, month and hour). If the missing countries together exceed
    :data:`MAX_STAND_IN_SHARE` of a column in any hour, :class:`EuPowerIncompleteError`.
    Returns the frame and the stood-in countries (empty when all loaded).
    """
    frames, not_found = fetch_country_power_frames(start, end, tolerate_missing_countries=True)
    total = _join_country_frames(frames, start, end)
    missing = _missing_country_hours(total, start, end)
    result = _sum_eu_columns(total)
    countries = tuple(c for c in GENERATION_COUNTRIES if missing[c].any())
    if not countries:
        return result, ()
    reasons = "; ".join(
        f"Land {c}: keine Daten (404)" if c in not_found else _missing_hours_summary(missing, c)
        for c in countries
    )
    months = result.index.month
    hours = result.index.hour
    for base, eu_name in EU_POWER_COLUMNS:
        missing_share = pd.Series(
            [
                sum(
                    shares.share(c, base, int(m), int(h))
                    for c in countries
                    if missing.at[slot, c]
                )
                for slot, m, h in zip(result.index, months, hours, strict=True)
            ],
            index=result.index,
        )
        worst = float(missing_share.abs().max()) if len(missing_share) else 0.0
        if worst > MAX_STAND_IN_SHARE:
            raise EuPowerIncompleteError(
                f"EU-Leistungsdaten für {start.isoformat()} bis {end.isoformat()} unvollständig "
                f"({reasons}); Ersatz über Länderanteile nicht möglich: Anteil an {eu_name} "
                f"bis {worst:.0%} (Grenze {MAX_STAND_IN_SHARE:.0%})."
            )
        result[eu_name] = result[eu_name] / (1.0 - missing_share)
    logger.warning(
        "EU-Leistung %s bis %s ohne %s (%s) — ersetzt über Länderanteile %s bis %s.",
        start.isoformat(),
        end.isoformat(),
        ", ".join(countries),
        reasons,
        shares.range_start,
        shares.range_end,
    )
    return result, countries


def fetch_eu_renewables_hourly(start: date, end: date) -> pd.DataFrame:
    """Summierte EU-Wind- und Solar-Erzeugung (MW) je Stunde."""
    power = fetch_eu_power_hourly(start, end)
    return power[["eu_wind_mw", "eu_solar_mw"]]


def fetch_at_day_ahead_hourly(start: date, end: date) -> pd.Series:
    """AT Day-Ahead EPEX in Cent/kWh (stündlich)."""
    frames: list[pd.Series] = []
    for chunk_start, chunk_end in month_ranges(start, end):
        payload = energy_charts.price(
            opendata_session.session(),
            bzn=AT_BIDDING_ZONE,
            start=chunk_start,
            end=chunk_end - timedelta(days=1),
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
    # One UTC day earlier: the first local hours of ``start`` belong to the previous UTC day.
    payload = open_meteo.archive(
        opendata_session.session(),
        latitude=point.latitude,
        longitude=point.longitude,
        start_date=start - timedelta(days=1),
        end_date=end - timedelta(days=1),
        hourly=EU_WEATHER_VARS,
        cached=True,
    )
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    wind = hourly.get("wind_speed_10m") or []
    radiation = hourly.get("shortwave_radiation") or []
    if not times or len(times) != len(wind) or len(times) != len(radiation):
        raise ValueError(f"Open-Meteo unvollständig für {point.name}.")
    tz = planning_timezone()
    index = pd.DatetimeIndex(
        [
            normalize_hour_slot(datetime.fromisoformat(str(ts)).replace(tzinfo=timezone.utc).astimezone(tz))
            for ts in times
        ]
    )
    frame = pd.DataFrame(
        {
            "wind_speed_kmh": wind,
            "shortwave_radiation_wm2": radiation,
        },
        index=index,
    )
    first = datetime.combine(start, datetime.min.time(), tzinfo=tz)
    stop = datetime.combine(end, datetime.min.time(), tzinfo=tz)
    return frame.loc[(frame.index >= first) & (frame.index < stop)]


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
    # Real clock: Open-Meteo counts forecast_days from the request's real today.
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
            normalize_hour_slot(datetime.fromisoformat(str(ts)).replace(tzinfo=timezone.utc).astimezone(tz))
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
    payload = open_meteo.forecast(
        opendata_session.session(),
        latitude=point.latitude,
        longitude=point.longitude,
        forecast_days=forecast_days,
        hourly=EU_WEATHER_VARS,
    )
    try:
        return _hourly_frame_from_open_meteo_payload(payload)
    except ValueError as exc:
        raise ValueError(f"{exc} ({point.name})") from exc


def _fetch_open_meteo_forecast_grid(*, forecast_days: int) -> dict[str, pd.DataFrame]:
    """One multi-location Open-Meteo call for the full EU weather grid."""
    payload = open_meteo.forecast(
        opendata_session.session(),
        latitude=[p.latitude for p in WEATHER_GRID],
        longitude=[p.longitude for p in WEATHER_GRID],
        forecast_days=forecast_days,
        hourly=EU_WEATHER_VARS,
    )
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


def fetch_eu_weather_forecast_hourly(start: date, end: date) -> pd.DataFrame:
    """Kapazitätsgewichteter EU-Wetterprognose-Mittelwert (Open-Meteo Forecast)."""
    forecast_days = _forecast_days_for_range(start, end)
    try:
        point_frames = _fetch_open_meteo_forecast_grid(forecast_days=forecast_days)
    except (OSError, ValueError):  # requests errors are OSError
        point_frames = {
            point.name: _fetch_open_meteo_forecast_point(
                point, forecast_days=forecast_days
            )
            for point in WEATHER_GRID
        }
    result = _weighted_eu_weather_from_points(point_frames)
    mask = (result.index.date >= start) & (result.index.date < end)
    return result.loc[mask].sort_index()


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
