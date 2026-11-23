"""Open-Meteo archive: payload parsing, irradiance conversion and the climate bundle type.

Split from ``data.open_meteo_solar_archive`` (KPI refactor); that module re-exports these
names. Pure functions without network or cache access: the fetch and cache functions that
tests patch stay in ``data.open_meteo_solar_archive``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from data.eu_market_features import month_ranges
from data.solar_horizon import DNI_VAR, HorizonProfile, shade_hourly_payload


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
