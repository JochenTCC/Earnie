"""Open-Meteo archive irradiance and temperature for PV / solar-thermal synthesis."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
import json
import threading

import pandas as pd

from data import opendata_session
from data.eu_market_features import month_ranges
from data.solar_horizon import DNI_VAR, HorizonProfile, shade_hourly_payload
from opendata import FetchBudgetExceeded, fetch_budget, open_meteo
from runtime_store.env_vars import read_env

OPEN_METEO_ARCHIVE = open_meteo.ARCHIVE_URL
# "_utc": files written before the UTC-request fix hold timestamps shifted by the UTC offset
# of the fetch day (Open-Meteo applies one fixed offset per response), so they are not reused.
OPEN_METEO_CACHE_DIR = Path("data/cache/open_meteo_utc")
HOURLY_VAR = "global_tilted_irradiance"
HOURLY_VAR_DAY1_FORECAST = f"{HOURLY_VAR}_previous_day1"
DNI_VAR_DAY1_FORECAST = f"{DNI_VAR}_previous_day1"
HOURLY_TEMP_VAR = "temperature_2m"
REFERENCE_WM2 = 1000.0
DEFAULT_THERMAL_EFFICIENCY = 0.40
# The download budget is the shared one of ``opendata`` (all requests inside the block).
ClimateFetchBudgetExceeded = FetchBudgetExceeded
climate_fetch_budget = fetch_budget


# Process-wide mem-cache: disk JSON → bundle; invalidate on file mtime change.
_bundle_mem_cache: dict[str, tuple[int, "OpenMeteoClimateBundle"]] = {}
_bundle_mem_lock = threading.Lock()
# Shaded bundles (SUSI P3a) are not written to disk:
# (raw file, horizon token) -> (mtime of the raw file, bundle).
_shaded_mem_cache: "OrderedDict[tuple[str, str], tuple[int, OpenMeteoClimateBundle]]" = OrderedDict()
_SHADED_MEM_MAX = 8
RAW_CACHE_VERSION = 1


def clear_open_meteo_bundle_mem_cache() -> None:
    """Reset in-process climate bundle cache (tests / forced reload)."""
    with _bundle_mem_lock:
        _bundle_mem_cache.clear()
        _shaded_mem_cache.clear()


@dataclass(frozen=True)
class TiltedSurface:
    """Geneigte Fläche für Open-Meteo global_tilted_irradiance."""

    tilt_deg: float
    azimuth_deg: float


def irradiance_wm2_to_pv_kw(irradiance_wm2: float | None, kwp: float) -> float:
    if irradiance_wm2 is None or kwp <= 0.0:
        return 0.0
    return round(max(0.0, float(irradiance_wm2) / REFERENCE_WM2 * kwp), 3)


def irradiance_wm2_to_thermal_kwh(
    irradiance_wm2: float | None,
    area_m2: float,
    *,
    eta: float = DEFAULT_THERMAL_EFFICIENCY,
) -> float:
    """Thermischer Stundenertrag (kWh_th) aus Einstrahlung auf Kollektorfläche."""
    if irradiance_wm2 is None or area_m2 <= 0.0:
        return 0.0
    return max(0.0, float(irradiance_wm2) / REFERENCE_WM2 * area_m2 * eta)


def last_full_archive_year(*, reference: date | None = None) -> int:
    """Letztes vollständiges Archiv-Kalenderjahr (z. B. 2025 bei Referenz 2026-07-13).

    Ohne ``reference`` gilt ``EARNIE_CLIMATE_REFERENCE_YEAR``, wenn gesetzt: Ein eingefrorener
    Lauf (Studie mit anderem Preisjahr) rechnet Wärmemodell, Grundlast und Profile mit diesem
    Archivjahr. Ein Jahr nach dem letzten vollen Archivjahr ist ein Fehler.
    """
    if reference is not None:
        return reference.year - 1
    from runtime_store.env_vars import read_climate_reference_year
    from runtime_store.planning_clock import planning_now

    natural = planning_now().year - 1
    pinned = read_climate_reference_year()
    if pinned is None:
        return natural
    if pinned > natural:
        raise ValueError(
            f"EARNIE_CLIMATE_REFERENCE_YEAR={pinned} liegt nach dem letzten vollen Archivjahr {natural}."
        )
    return pinned


def archive_latest_complete_date() -> date:
    """Letzter Kalendertag mit vollständigen Open-Meteo-Archivdaten.

    ``EARNIE_OPEN_METEO_AS_OF`` (ISO-Datum) pinnt den Tag: Der Cache-Schlüssel des
    laufenden Jahres bleibt dann stabil (eingefrorene Offline-Läufe). Ein Datum nach
    dem tatsächlich letzten Archivtag ist ein Fehler.
    """
    from data.price_forecast_live import _archive_latest_complete_day

    latest = _archive_latest_complete_day()
    raw = read_env("OPEN_METEO_AS_OF")
    if not raw:
        return latest
    try:
        pinned = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"EARNIE_OPEN_METEO_AS_OF={raw!r} ist kein ISO-Datum (JJJJ-MM-TT)."
        ) from exc
    if pinned > latest:
        raise ValueError(
            f"EARNIE_OPEN_METEO_AS_OF={raw} liegt nach dem letzten Archivtag "
            f"{latest.isoformat()}."
        )
    return pinned


def _cap_inclusive_end(end: date) -> date:
    latest = archive_latest_complete_date()
    return min(end, latest)


def utc_hourly_index_to_local_naive(
    utc_times: pd.DatetimeIndex, timezone: str
) -> pd.DatetimeIndex:
    """UTC timestamps (naive or aware) -> local wall-clock stamps of ``timezone`` (naive).

    The archive is requested with ``timezone=UTC`` because with a zone name Open-Meteo
    applies ONE fixed UTC offset to the whole response (the offset valid on the request
    day, not per date), which shifts summer or winter hours by 1 h depending on when the
    data was fetched.
    """
    if utc_times.tz is None:
        utc_times = utc_times.tz_localize("UTC")
    return utc_times.tz_convert(timezone).tz_localize(None)


def _parse_hourly_times(times: list[str]) -> list[datetime]:
    parsed: list[datetime] = []
    for raw in times:
        text = str(raw).replace("Z", "+00:00")
        moment = datetime.fromisoformat(text)
        if moment.tzinfo is not None:
            moment = moment.replace(tzinfo=None)
        parsed.append(moment)
    return parsed


def _concat_hourly_chunks(chunks: list[pd.Series]) -> pd.Series:
    if not chunks:
        return pd.Series(dtype=float)
    series = pd.concat(chunks)
    return series[~series.index.duplicated(keep="last")].sort_index()


def _hourly_series_from_payload(
    payload: dict[str, Any],
    *,
    hourly_vars: str,
    start: date,
    end: date,
    timezone: str,
) -> dict[str, pd.Series]:
    """Parse a UTC archive payload into local wall-clock series of ``timezone``.

    The repeated hour of the autumn DST change is averaged; the skipped spring hour is absent.
    """
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise ValueError(
            f"Open-Meteo archive unvollständig ({start}..{end - timedelta(days=1)}): "
            "keine Zeitstempel."
        )
    index = utc_hourly_index_to_local_naive(
        pd.DatetimeIndex(_parse_hourly_times(times)), timezone
    )
    var_names = [name.strip() for name in hourly_vars.split(",")]
    result: dict[str, pd.Series] = {}
    for var_name in var_names:
        values = hourly.get(var_name) or []
        if len(values) != len(times):
            raise ValueError(
                f"Open-Meteo archive unvollständig ({start}..{end - timedelta(days=1)}): "
                f"{var_name} hat {len(values)} Werte für {len(times)} Zeitstempel."
            )
        series = pd.Series(values, index=index, dtype=float)
        result[var_name] = series.groupby(level=0).mean() if series.index.has_duplicates else series
    return result


def _fetch_hourly_archive_chunk(
    *,
    lat: float,
    lon: float,
    timezone: str,
    start: date,
    end: date,
    hourly_vars: str,
    extra_params: dict[str, Any] | None = None,
    fetch=open_meteo.archive,
    payload_transform=None,
) -> dict[str, pd.Series]:
    # One UTC day earlier: the first local hours of ``start`` belong to the previous UTC day.
    payload = fetch(
        opendata_session.session(),
        latitude=lat,
        longitude=lon,
        start_date=start - timedelta(days=1),
        end_date=end - timedelta(days=1),
        hourly=hourly_vars,
        extra_params=extra_params,
    )
    return _chunk_series(
        payload,
        timezone=timezone,
        start=start,
        end=end,
        hourly_vars=hourly_vars,
        payload_transform=payload_transform,
    )


def _chunk_series(
    payload: dict[str, Any],
    *,
    timezone: str,
    start: date,
    end: date,
    hourly_vars: str,
    payload_transform=None,
) -> dict[str, pd.Series]:
    """Local wall-clock series of ``[start, end)`` from one UTC archive payload."""
    if payload_transform is not None:
        # On the UTC stamps, before the local wall clock: the sun position needs real time.
        payload = payload_transform(payload)
    series_by_var = _hourly_series_from_payload(
        payload,
        hourly_vars=hourly_vars,
        start=start,
        end=end,
        timezone=timezone,
    )
    first, stop = pd.Timestamp(start), pd.Timestamp(end)
    return {
        name: series.loc[(series.index >= first) & (series.index < stop)]
        for name, series in series_by_var.items()
    }


def fetch_hourly_temperature_c_series(
    start: date,
    end: date,
    *,
    lat: float,
    lon: float,
    timezone: str,
) -> pd.Series:
    """Stündliche Lufttemperatur (°C) aus Open-Meteo archive."""
    if end < start:
        raise ValueError("Open-Meteo Temperatur: end muss nicht vor start liegen.")
    chunks: list[pd.Series] = []
    for chunk_start, chunk_end in month_ranges(start, end + timedelta(days=1)):
        payload = _fetch_hourly_archive_chunk(
            lat=lat,
            lon=lon,
            timezone=timezone,
            start=chunk_start,
            end=chunk_end,
            hourly_vars=HOURLY_TEMP_VAR,
        )
        chunks.append(payload[HOURLY_TEMP_VAR])
    return _concat_hourly_chunks(chunks)


def _tilted_request(
    tilted_var: str,
    dni_var: str,
    *,
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    horizon: HorizonProfile | None,
):
    """(hourly variables, extra chunk-fetch keywords) of a tilted-irradiance request.

    Without a horizon the request and the chunk fetch are the ones from before SUSI P3a
    (same parameters, same cache and shadow keys, no extra keyword). The mask uses the same
    whole degrees Open-Meteo is asked for.
    """
    if horizon is None:
        return tilted_var, {}

    def _shade(payload: dict) -> dict:
        return shade_hourly_payload(
            payload,
            tilted_var=tilted_var,
            dni_var=dni_var,
            lat=lat,
            lon=lon,
            tilt_deg=float(int(round(tilt))),
            azimuth_deg=float(int(round(azimuth))),
            horizon=horizon,
        )

    return f"{tilted_var},{dni_var}", {"payload_transform": _shade}


def fetch_hourly_tilted_irradiance_wm2_series(
    start: date,
    end: date,
    *,
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    timezone: str,
    horizon: HorizonProfile | None = None,
) -> pd.Series:
    """Stündliche geneigte Einstrahlung (W/m²) für eine Oberfläche.

    With ``horizon`` the direct beam is removed while the sun is behind it (SUSI P3a); only
    then the request also asks for ``direct_normal_irradiance``.
    """
    if end < start:
        raise ValueError("Open-Meteo Irradianz: end muss nicht vor start liegen.")
    hourly_vars, transform = _tilted_request(
        HOURLY_VAR, DNI_VAR, lat=lat, lon=lon, tilt=tilt, azimuth=azimuth, horizon=horizon
    )
    chunks: list[pd.Series] = []
    for chunk_start, chunk_end in month_ranges(start, end + timedelta(days=1)):
        payload = _fetch_hourly_archive_chunk(
            lat=lat,
            lon=lon,
            timezone=timezone,
            start=chunk_start,
            end=chunk_end,
            hourly_vars=hourly_vars,
            extra_params={
                "tilt": int(round(tilt)),
                "azimuth": int(round(azimuth)),
            },
            **transform,
        )
        chunks.append(payload[HOURLY_VAR])
    return _concat_hourly_chunks(chunks)


def fetch_hourly_tilted_irradiance_day1_forecast_wm2_series(
    start: date,
    end: date,
    *,
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    timezone: str,
    horizon: HorizonProfile | None = None,
) -> pd.Series:
    """Tilted irradiance as forecast 24 h earlier, local wall clock; NaN where no run is archived.

    With ``horizon`` shaded like the archive series, with the DNI of the same forecast run.
    """
    if end < start:
        raise ValueError("Open-Meteo Prognosearchiv: end muss nicht vor start liegen.")
    hourly_vars, transform = _tilted_request(
        HOURLY_VAR_DAY1_FORECAST,
        DNI_VAR_DAY1_FORECAST,
        lat=lat,
        lon=lon,
        tilt=tilt,
        azimuth=azimuth,
        horizon=horizon,
    )
    chunks: list[pd.Series] = []
    for chunk_start, chunk_end in month_ranges(start, end + timedelta(days=1)):
        payload = _fetch_hourly_archive_chunk(
            lat=lat,
            lon=lon,
            timezone=timezone,
            start=chunk_start,
            end=chunk_end,
            hourly_vars=hourly_vars,
            extra_params={
                "tilt": int(round(tilt)),
                "azimuth": int(round(azimuth)),
            },
            fetch=open_meteo.previous_runs,
            **transform,
        )
        chunks.append(payload[HOURLY_VAR_DAY1_FORECAST])
    return _concat_hourly_chunks(chunks)


def _fetch_pv_kw_chunk(
    *,
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    kwp: float,
    timezone: str,
    start: date,
    end: date,
) -> pd.Series:
    payload = _fetch_hourly_archive_chunk(
        lat=lat,
        lon=lon,
        timezone=timezone,
        start=start,
        end=end,
        hourly_vars=HOURLY_VAR,
        extra_params={
            "tilt": int(round(tilt)),
            "azimuth": int(round(azimuth)),
        },
    )
    irradiance = payload[HOURLY_VAR]
    return irradiance.apply(lambda value: irradiance_wm2_to_pv_kw(value, kwp))


def fetch_hourly_pv_kw_series(
    start: date,
    end: date,
    *,
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    kwp: float,
    timezone: str,
) -> pd.Series:
    """Stündliche PV-Leistung (kW) aus Open-Meteo global_tilted_irradiance."""
    if end < start:
        raise ValueError("Open-Meteo PV: end muss nicht vor start liegen.")
    if kwp <= 0.0:
        return pd.Series(dtype=float)

    chunks: list[pd.Series] = []
    for chunk_start, chunk_end in month_ranges(start, end + timedelta(days=1)):
        chunks.append(
            _fetch_pv_kw_chunk(
                lat=lat,
                lon=lon,
                tilt=tilt,
                azimuth=azimuth,
                kwp=kwp,
                timezone=timezone,
                start=chunk_start,
                end=chunk_end,
            )
        )
    return _concat_hourly_chunks(chunks)


@dataclass
class OpenMeteoClimateBundle:
    """Hourly Open-Meteo archive series for a contiguous date window."""

    temperature_c: pd.Series
    tilted_wm2: dict[TiltedSurface, pd.Series]

    def _slot_key(self, slot: datetime) -> pd.Timestamp:
        return pd.Timestamp(slot.replace(minute=0, second=0, microsecond=0))

    def _irradiance_wm2_at(self, surface: TiltedSurface, slot: datetime) -> float | None:
        series = self.tilted_wm2.get(surface)
        if series is None or series.empty:
            return None
        key = self._slot_key(slot)
        if key not in series.index:
            return None
        value = series.loc[key]
        if pd.isna(value):
            return None
        return float(value)

    def pv_kw_at(self, surface: TiltedSurface, kwp: float, slot: datetime) -> float:
        if kwp <= 0.0:
            return 0.0
        wm2 = self._irradiance_wm2_at(surface, slot)
        return irradiance_wm2_to_pv_kw(wm2, kwp)

    def thermal_kwh_at(
        self,
        surface: TiltedSurface,
        area_m2: float,
        slot: datetime,
        *,
        eta: float = DEFAULT_THERMAL_EFFICIENCY,
    ) -> float:
        wm2 = self._irradiance_wm2_at(surface, slot)
        return round(irradiance_wm2_to_thermal_kwh(wm2, area_m2, eta=eta), 6)

    def daily_mean_temperatures(self) -> tuple[list[date], list[float]]:
        if self.temperature_c.empty:
            raise ValueError("Open-MeteoClimateBundle: temperature_c ist leer.")
        grouped = self.temperature_c.groupby(self.temperature_c.index.date).mean()
        dates = sorted(grouped.index)
        return dates, [float(grouped[day]) for day in dates]

    def collector_surface_series(self, surface: TiltedSurface) -> pd.Series:
        series = self.tilted_wm2.get(surface)
        if series is None:
            raise KeyError(f"Keine Irradianz-Serie für Oberfläche {surface!r}.")
        return series


def _unique_surfaces(surfaces: list[TiltedSurface]) -> list[TiltedSurface]:
    seen: set[tuple[float, float]] = set()
    unique: list[TiltedSurface] = []
    for surface in surfaces:
        key = (round(surface.tilt_deg, 3), round(surface.azimuth_deg, 3))
        if key in seen:
            continue
        seen.add(key)
        unique.append(surface)
    return unique


def _surface_wm2_column(surface: TiltedSurface) -> str:
    return f"wm2_{round(surface.tilt_deg, 1)}_{round(surface.azimuth_deg, 1)}"


def _surface_cache_token(surfaces: list[TiltedSurface]) -> str:
    parts = [
        f"{round(surface.tilt_deg, 1)}_{round(surface.azimuth_deg, 1)}"
        for surface in sorted(surfaces, key=lambda item: (item.tilt_deg, item.azimuth_deg))
    ]
    return "-".join(parts) if parts else "none"


def _default_cache_dir() -> Path:
    """``EARNIE_OPEN_METEO_CACHE_PATH`` if set, else ``OPEN_METEO_CACHE_DIR``."""
    override = read_env("OPEN_METEO_CACHE_PATH")
    return Path(override) if override else OPEN_METEO_CACHE_DIR


def open_meteo_cache_path(
    lat: float,
    lon: float,
    timezone: str,
    start: date,
    end: date,
    surfaces: list[TiltedSurface],
    *,
    cache_dir: Path | None = None,
    horizon: HorizonProfile | None = None,
) -> Path:
    token = _surface_cache_token(_unique_surfaces(surfaces))
    if horizon is not None:
        # Unshaded UTC payloads with DNI, the same file for every horizon; the mask is
        # applied on reading. Without a horizon the name is unchanged.
        token = f"{token}_hzraw"
    tz_token = timezone.replace("/", "-")
    name = (
        f"{lat:.4f}_{lon:.4f}_{start.isoformat()}_{end.isoformat()}_"
        f"{tz_token}_{token}.json"
    )
    return (cache_dir or _default_cache_dir()) / name


def _bundle_to_frame(bundle: OpenMeteoClimateBundle) -> pd.DataFrame:
    frame = pd.DataFrame({"temperature_c": bundle.temperature_c})
    for surface, series in bundle.tilted_wm2.items():
        frame[_surface_wm2_column(surface)] = series
    return frame


def _frame_to_bundle(
    frame: pd.DataFrame,
    surfaces: list[TiltedSurface],
) -> OpenMeteoClimateBundle:
    if "temperature_c" not in frame.columns:
        raise ValueError("Open-Meteo cache: Spalte temperature_c fehlt.")
    temperature_c = frame["temperature_c"]
    tilted_wm2: dict[TiltedSurface, pd.Series] = {}
    for surface in _unique_surfaces(surfaces):
        column = _surface_wm2_column(surface)
        if column not in frame.columns:
            raise ValueError(f"Open-Meteo cache: Spalte {column} fehlt.")
        tilted_wm2[surface] = frame[column]
    return OpenMeteoClimateBundle(
        temperature_c=temperature_c,
        tilted_wm2=tilted_wm2,
    )


def _cache_path_key(path: Path) -> str:
    return str(path.resolve())


def _store_bundle_mem(path: Path, bundle: OpenMeteoClimateBundle) -> None:
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return
    with _bundle_mem_lock:
        _bundle_mem_cache[_cache_path_key(path)] = (mtime_ns, bundle)


def _load_bundle_from_cache(
    lat: float,
    lon: float,
    timezone: str,
    start: date,
    end: date,
    surfaces: list[TiltedSurface],
    *,
    cache_dir: Path | None = None,
) -> OpenMeteoClimateBundle | None:
    path = open_meteo_cache_path(
        lat,
        lon,
        timezone,
        start,
        end,
        surfaces,
        cache_dir=cache_dir,
    )
    if not path.exists():
        return None
    key = _cache_path_key(path)
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return None
    with _bundle_mem_lock:
        hit = _bundle_mem_cache.get(key)
        if hit is not None and hit[0] == mtime_ns:
            return hit[1]
    try:
        frame = pd.read_json(path, orient="split")
        frame.index = pd.to_datetime(frame.index)
    except Exception as exc:
        raise ValueError(f"Open-Meteo cache unlesbar ({path}): {exc}") from exc
    bundle = _frame_to_bundle(frame, surfaces)
    with _bundle_mem_lock:
        _bundle_mem_cache[key] = (mtime_ns, bundle)
    return bundle


def _save_bundle_to_cache(
    bundle: OpenMeteoClimateBundle,
    lat: float,
    lon: float,
    timezone: str,
    start: date,
    end: date,
    surfaces: list[TiltedSurface],
    *,
    cache_dir: Path | None = None,
) -> None:
    path = open_meteo_cache_path(
        lat,
        lon,
        timezone,
        start,
        end,
        surfaces,
        cache_dir=cache_dir,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    _bundle_to_frame(bundle).to_json(path, orient="split", date_format="iso")
    _store_bundle_mem(path, bundle)


def _fetch_archive_payload(
    *,
    lat: float,
    lon: float,
    start: date,
    end: date,
    hourly_vars: str,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Raw UTC archive payload of the chunk ``[start, end)`` (one UTC day earlier, as above)."""
    return open_meteo.archive(
        opendata_session.session(),
        latitude=lat,
        longitude=lon,
        start_date=start - timedelta(days=1),
        end_date=end - timedelta(days=1),
        hourly=hourly_vars,
        extra_params=extra_params,
    )


def _raw_key(hourly_vars: str, start: date, end: date, surface: TiltedSurface | None) -> str:
    where = ""
    if surface is not None:
        where = f"|{int(round(surface.tilt_deg))}|{int(round(surface.azimuth_deg))}"
    return f"{hourly_vars}|{start.isoformat()}|{end.isoformat()}{where}"


def _raw_requests(
    start: date, end: date, surfaces: list[TiltedSurface]
) -> list[tuple[str, date, date, TiltedSurface | None]]:
    """(hourly variables, chunk start, chunk end, surface or None for the temperature)."""
    chunks = list(month_ranges(start, end + timedelta(days=1)))
    requests = [(HOURLY_TEMP_VAR, first, stop, None) for first, stop in chunks]
    for surface in surfaces:
        requests += [(f"{HOURLY_VAR},{DNI_VAR}", first, stop, surface) for first, stop in chunks]
    return requests


def _fetch_raw_payloads(
    start: date, end: date, *, lat: float, lon: float, surfaces: list[TiltedSurface]
) -> dict[str, dict]:
    payloads: dict[str, dict] = {}
    for hourly_vars, first, stop, surface in _raw_requests(start, end, surfaces):
        extra = None
        if surface is not None:
            extra = {
                "tilt": int(round(surface.tilt_deg)),
                "azimuth": int(round(surface.azimuth_deg)),
            }
        payload = _fetch_archive_payload(
            lat=lat, lon=lon, start=first, end=stop, hourly_vars=hourly_vars, extra_params=extra
        )
        payloads[_raw_key(hourly_vars, first, stop, surface)] = {"hourly": payload.get("hourly")}
    return payloads


def _load_raw_from_cache(path: Path) -> dict[str, dict] | None:
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Open-Meteo cache unlesbar ({path}): {exc}") from exc
    if not isinstance(doc, dict) or doc.get("version") != RAW_CACHE_VERSION:
        raise ValueError(f"Open-Meteo cache ({path}): unbekannte Version.")
    return doc["payloads"]


def _save_raw_to_cache(path: Path, payloads: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"version": RAW_CACHE_VERSION, "payloads": payloads})
    path.write_text(text, encoding="utf-8", newline="\n")


def _bundle_from_raw(
    payloads: dict[str, dict],
    start: date,
    end: date,
    *,
    lat: float,
    lon: float,
    timezone: str,
    surfaces: list[TiltedSurface],
    horizon: HorizonProfile,
    source: str,
) -> OpenMeteoClimateBundle:
    """Temperature and shaded surface series from the unshaded UTC payloads."""
    temperature: list[pd.Series] = []
    tilted: dict[TiltedSurface, list[pd.Series]] = {surface: [] for surface in surfaces}
    for hourly_vars, first, stop, surface in _raw_requests(start, end, surfaces):
        key = _raw_key(hourly_vars, first, stop, surface)
        if key not in payloads:
            raise ValueError(f"Open-Meteo cache unvollständig ({source}): {key} fehlt.")
        transform: dict[str, Any] = {}
        if surface is not None:
            _vars, transform = _tilted_request(
                HOURLY_VAR,
                DNI_VAR,
                lat=lat,
                lon=lon,
                tilt=surface.tilt_deg,
                azimuth=surface.azimuth_deg,
                horizon=horizon,
            )
        series = _chunk_series(
            payloads[key],
            timezone=timezone,
            start=first,
            end=stop,
            hourly_vars=hourly_vars,
            **transform,
        )
        if surface is None:
            temperature.append(series[HOURLY_TEMP_VAR])
        else:
            tilted[surface].append(series[HOURLY_VAR])
    return OpenMeteoClimateBundle(
        temperature_c=_concat_hourly_chunks(temperature),
        tilted_wm2={surface: _concat_hourly_chunks(chunks) for surface, chunks in tilted.items()},
    )


def _build_shaded_bundle(
    start: date,
    end: date,
    *,
    lat: float,
    lon: float,
    timezone: str,
    surfaces: list[TiltedSurface],
    use_cache: bool,
    cache_dir: Path | None,
    horizon: HorizonProfile,
) -> OpenMeteoClimateBundle:
    """Bundle with a horizon: the weather is fetched once per site, the mask per horizon.

    The file holds the unshaded payloads with DNI, so a changed horizon needs no request.
    """
    path = open_meteo_cache_path(
        lat, lon, timezone, start, end, surfaces, cache_dir=cache_dir, horizon=horizon
    )
    mem_key = (_cache_path_key(path), horizon.token())
    payloads = None
    if use_cache:
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = None
        if mtime_ns is not None:
            with _bundle_mem_lock:
                hit = _shaded_mem_cache.get(mem_key)
                if hit is not None and hit[0] == mtime_ns:
                    _shaded_mem_cache.move_to_end(mem_key)
                    return hit[1]
        payloads = _load_raw_from_cache(path)
    if payloads is None:
        payloads = _fetch_raw_payloads(start, end, lat=lat, lon=lon, surfaces=surfaces)
        if use_cache:
            _save_raw_to_cache(path, payloads)
    bundle = _bundle_from_raw(
        payloads,
        start,
        end,
        lat=lat,
        lon=lon,
        timezone=timezone,
        surfaces=surfaces,
        horizon=horizon,
        source=str(path),
    )
    if use_cache:
        mtime_ns = path.stat().st_mtime_ns
        with _bundle_mem_lock:
            _shaded_mem_cache[mem_key] = (mtime_ns, bundle)
            _shaded_mem_cache.move_to_end(mem_key)
            while len(_shaded_mem_cache) > _SHADED_MEM_MAX:
                _shaded_mem_cache.popitem(last=False)
    return bundle


def build_open_meteo_climate_bundle(
    start: date,
    end: date,
    *,
    lat: float,
    lon: float,
    timezone: str,
    surfaces: list[TiltedSurface],
    use_cache: bool = True,
    cache_dir: Path | None = None,
    horizon: HorizonProfile | None = None,
) -> OpenMeteoClimateBundle:
    """
    Lädt Temperatur und geneigte Einstrahlung für alle Oberflächen.
    API-Fehler werden durchgereicht (kein Fallback).

    With ``horizon`` every surface series is shaded (SUSI P3a). The cache file then holds the
    unshaded data with DNI and is the same for every horizon.
    """
    end = _cap_inclusive_end(end)
    if end < start:
        raise ValueError(
            f"Open-Meteo Klima: kein Archiv für {start}..{end} "
            f"(letzter Archivtag: {archive_latest_complete_date().isoformat()})."
        )
    unique_surfaces = _unique_surfaces(surfaces)
    if horizon is not None:
        return _build_shaded_bundle(
            start,
            end,
            lat=lat,
            lon=lon,
            timezone=timezone,
            surfaces=unique_surfaces,
            use_cache=use_cache,
            cache_dir=cache_dir,
            horizon=horizon,
        )
    if use_cache:
        cached = _load_bundle_from_cache(
            lat,
            lon,
            timezone,
            start,
            end,
            unique_surfaces,
            cache_dir=cache_dir,
        )
        if cached is not None:
            return cached
    temperature_c = fetch_hourly_temperature_c_series(
        start,
        end,
        lat=lat,
        lon=lon,
        timezone=timezone,
    )
    tilted_wm2: dict[TiltedSurface, pd.Series] = {}
    for surface in unique_surfaces:
        tilted_wm2[surface] = fetch_hourly_tilted_irradiance_wm2_series(
            start,
            end,
            lat=lat,
            lon=lon,
            tilt=surface.tilt_deg,
            azimuth=surface.azimuth_deg,
            timezone=timezone,
        )
    bundle = OpenMeteoClimateBundle(
        temperature_c=temperature_c,
        tilted_wm2=tilted_wm2,
    )
    if use_cache:
        _save_bundle_to_cache(
            bundle,
            lat,
            lon,
            timezone,
            start,
            end,
            unique_surfaces,
            cache_dir=cache_dir,
        )
    return bundle


def build_open_meteo_climate_bundle_for_year(
    year: int,
    *,
    lat: float,
    lon: float,
    timezone: str,
    surfaces: list[TiltedSurface],
    use_cache: bool = True,
    cache_dir: Path | None = None,
    horizon: HorizonProfile | None = None,
) -> OpenMeteoClimateBundle:
    """Volles Kalenderjahr (01-01 .. 12-31)."""
    return build_open_meteo_climate_bundle(
        date(year, 1, 1),
        date(year, 12, 31),
        lat=lat,
        lon=lon,
        timezone=timezone,
        surfaces=surfaces,
        use_cache=use_cache,
        cache_dir=cache_dir,
        horizon=horizon,
    )
