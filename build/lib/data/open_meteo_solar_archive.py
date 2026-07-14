"""Open-Meteo archive irradiance and temperature for PV / solar-thermal synthesis."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import config
from data.eu_market_features import month_ranges

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_CACHE_DIR = Path("data/cache/open_meteo")
HOURLY_VAR = "global_tilted_irradiance"
HOURLY_TEMP_VAR = "temperature_2m"
REFERENCE_WM2 = 1000.0
DEFAULT_THERMAL_EFFICIENCY = 0.40


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
    """Letztes vollständiges Archiv-Kalenderjahr (z. B. 2025 bei Referenz 2026-07-13)."""
    if reference is None:
        reference = date.today()
    return reference.year - 1


def archive_latest_complete_date() -> date:
    """Letzter Kalendertag mit vollständigen Open-Meteo-Archivdaten."""
    from data.price_forecast_live import _archive_latest_complete_day

    return _archive_latest_complete_day()


def _cap_inclusive_end(end: date) -> date:
    latest = archive_latest_complete_date()
    return min(end, latest)


def _resolve_installation_params() -> tuple[float, float, float, float, float, str]:
    lat = float(config.get("LATITUDE", cast=float))
    lon = float(config.get("LONGITUDE", cast=float))
    tilt = float(config.get("PV_TILT", cast=float))
    azimuth = float(config.get("PV_AZIMUTH", cast=float))
    kwp = float(config.get("PV_KWP", cast=float))
    timezone = str(config.get_planning_timezone())
    return lat, lon, tilt, azimuth, kwp, timezone


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


def _fetch_hourly_archive_chunk(
    *,
    lat: float,
    lon: float,
    timezone: str,
    start: date,
    end: date,
    hourly_vars: str,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, pd.Series]:
    params: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": (end - timedelta(days=1)).isoformat(),
        "hourly": hourly_vars,
        "timezone": timezone,
    }
    if extra_params:
        params.update(extra_params)
    response = requests.get(
        OPEN_METEO_ARCHIVE,
        params=params,
        timeout=config.get_global_timeout(),
    )
    response.raise_for_status()
    payload = response.json()
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise ValueError(
            f"Open-Meteo archive unvollständig ({start}..{end - timedelta(days=1)}): "
            "keine Zeitstempel."
        )
    index = pd.DatetimeIndex(_parse_hourly_times(times))
    var_names = [name.strip() for name in hourly_vars.split(",")]
    result: dict[str, pd.Series] = {}
    for var_name in var_names:
        values = hourly.get(var_name) or []
        if len(values) != len(times):
            raise ValueError(
                f"Open-Meteo archive unvollständig ({start}..{end - timedelta(days=1)}): "
                f"{var_name} hat {len(values)} Werte für {len(times)} Zeitstempel."
            )
        result[var_name] = pd.Series(values, index=index, dtype=float)
    return result


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


def fetch_hourly_tilted_irradiance_wm2_series(
    start: date,
    end: date,
    *,
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    timezone: str,
) -> pd.Series:
    """Stündliche geneigte Einstrahlung (W/m²) für eine Oberfläche."""
    if end < start:
        raise ValueError("Open-Meteo Irradianz: end muss nicht vor start liegen.")
    chunks: list[pd.Series] = []
    for chunk_start, chunk_end in month_ranges(start, end + timedelta(days=1)):
        payload = _fetch_hourly_archive_chunk(
            lat=lat,
            lon=lon,
            timezone=timezone,
            start=chunk_start,
            end=chunk_end,
            hourly_vars=HOURLY_VAR,
            extra_params={
                "tilt": int(round(tilt)),
                "azimuth": int(round(azimuth)),
            },
        )
        chunks.append(payload[HOURLY_VAR])
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


def open_meteo_cache_path(
    lat: float,
    lon: float,
    timezone: str,
    start: date,
    end: date,
    surfaces: list[TiltedSurface],
    *,
    cache_dir: Path | None = None,
) -> Path:
    token = _surface_cache_token(_unique_surfaces(surfaces))
    tz_token = timezone.replace("/", "-")
    name = (
        f"{lat:.4f}_{lon:.4f}_{start.isoformat()}_{end.isoformat()}_"
        f"{tz_token}_{token}.json"
    )
    return (cache_dir or OPEN_METEO_CACHE_DIR) / name


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
    try:
        frame = pd.read_json(path, orient="split")
        frame.index = pd.to_datetime(frame.index)
    except Exception as exc:
        raise ValueError(f"Open-Meteo cache unlesbar ({path}): {exc}") from exc
    return _frame_to_bundle(frame, surfaces)


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
) -> OpenMeteoClimateBundle:
    """
    Lädt Temperatur und geneigte Einstrahlung für alle Oberflächen.
    API-Fehler werden durchgereicht (kein Fallback).
    """
    end = _cap_inclusive_end(end)
    if end < start:
        raise ValueError(
            f"Open-Meteo Klima: kein Archiv für {start}..{end} "
            f"(letzter Archivtag: {archive_latest_complete_date().isoformat()})."
        )
    unique_surfaces = _unique_surfaces(surfaces)
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
    )


class OpenMeteoPvLookup:
    """Maps naive local hour slots to PV kW from Open-Meteo archive data."""

    def __init__(
        self,
        series: pd.Series,
        *,
        kwp: float,
        fallback: Callable[[int, int, float], float],
    ) -> None:
        self._series = series
        self._kwp = kwp
        self._fallback = fallback

    def kw_at(self, slot: datetime) -> float:
        if self._kwp <= 0.0:
            return 0.0
        key = slot.replace(minute=0, second=0, microsecond=0)
        if key in self._series.index:
            return round(float(self._series.loc[key]), 3)
        return self._fallback(key.hour, key.month, self._kwp)


def build_open_meteo_pv_lookup(
    start: date,
    end: date,
    *,
    fallback: Callable[[int, int, float], float],
) -> OpenMeteoPvLookup:
    lat, lon, tilt, azimuth, kwp, timezone = _resolve_installation_params()
    if kwp <= 0.0:
        print("[INFO] PV deaktiviert (PV_KWP=0) – cons_data pv_kw bleibt 0.")
        return OpenMeteoPvLookup(pd.Series(dtype=float), kwp=kwp, fallback=fallback)

    try:
        series = fetch_hourly_pv_kw_series(
            start,
            end,
            lat=lat,
            lon=lon,
            tilt=tilt,
            azimuth=azimuth,
            kwp=kwp,
            timezone=timezone,
        )
    except Exception as exc:
        print(f"[WARN] Open-Meteo Solar Archive fehlgeschlagen: {exc}. Nutze PV-Fallback-Kurve.")
        return OpenMeteoPvLookup(pd.Series(dtype=float), kwp=kwp, fallback=fallback)

    expected_hours = int((datetime.combine(end, datetime.min.time()) - datetime.combine(start, datetime.min.time())).total_seconds() // 3600) + 24
    covered = len(series)
    print(
        f"[OK] Open-Meteo Solar Archive: {covered} Stunden PV geladen "
        f"({start}..{end}, {kwp:.1f} kWp, {tilt:.0f}°/{azimuth:.0f}°)."
    )
    if covered < expected_hours:
        print(
            f"[WARN] Open-Meteo PV: nur {covered}/{expected_hours} Stunden im Zeitraum – "
            "fehlende Slots nutzen PV-Fallback."
        )
    return OpenMeteoPvLookup(series, kwp=kwp, fallback=fallback)
