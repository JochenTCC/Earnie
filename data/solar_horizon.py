"""SUSI P3a — horizon shading: the direct beam is removed while the sun is behind the horizon.

A horizon is a list of (azimuth, elevation) points around the house (terrain, buildings,
trees). Azimuth as for the PV fields and Open-Meteo: 0° = south, -90° = east, 90° = west,
±180° = north. Between the points the elevation is interpolated linearly, also across ±180°.

Open-Meteo's hourly irradiance is the mean of the hour **before** its stamp. For every hour
the sun position is sampled ``SUB_SAMPLES`` times inside that hour, so the mask does not jump
at sunrise, sunset or where the sun crosses the horizon line:

    GTI_shaded = GTI − DNI × Σ(blocked_i × max(0, cos AOI_i)) / n_up

``n_up`` counts the samples with the sun above 0°: the hourly DNI is a mean over the whole
hour, the beam only exists while the sun is up. Diffuse and ground-reflected irradiance stay
(no sky model of our own; Open-Meteo's transposition is kept).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Sequence

HORIZON_KEY = "horizon"
HORIZON_SOURCE_KEY = "horizon_source"
SOURCE_NONE = "none"
SOURCE_MANUAL = "manual"
HORIZON_SOURCES: tuple[str, ...] = (SOURCE_NONE, SOURCE_MANUAL)
DNI_VAR = "direct_normal_irradiance"
SUB_SAMPLES = 4
MAX_ELEVATION_DEG = 90.0


@dataclass(frozen=True)
class HorizonProfile:
    """Horizon elevation by azimuth; ``points`` sorted by azimuth in [-180, 180)."""

    points: tuple[tuple[float, float], ...]

    def elevation_at(self, azimuth_deg: float) -> float:
        """Horizon elevation (°) at ``azimuth_deg``, linear between neighbours across ±180°."""
        azimuth = wrap_azimuth(azimuth_deg)
        points = self.points
        if len(points) == 1:
            return points[0][1]
        for (az0, el0), (az1, el1) in zip(points, points[1:]):
            if az0 <= azimuth <= az1:
                return el0 + (el1 - el0) * (azimuth - az0) / (az1 - az0)
        # Between the last point and the first one, across ±180°.
        az0, el0 = points[-1]
        az1, el1 = points[0]
        span = az1 + 360.0 - az0
        offset = azimuth - az0 if azimuth >= az0 else azimuth + 360.0 - az0
        return el0 + (el1 - el0) * offset / span

    def token(self) -> str:
        """Short stable id of the profile for cache keys and file names."""
        text = ";".join(f"{az:.2f}:{el:.2f}" for az, el in self.points)
        return hashlib.sha1(text.encode("ascii")).hexdigest()[:10]

    def as_list(self) -> list[dict[str, float]]:
        return [{"azimuth_deg": az, "elevation_deg": el} for az, el in self.points]


def wrap_azimuth(azimuth_deg: float) -> float:
    """Azimuth in [-180, 180)."""
    return (float(azimuth_deg) + 180.0) % 360.0 - 180.0


def _number(raw: Any, *, where: str) -> float:
    if isinstance(raw, bool) or raw is None or raw == "":
        raise ValueError(f"{where} muss eine Zahl sein (ist {raw!r}).")
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where} muss eine Zahl sein (ist {raw!r}).") from exc


def normalize_horizon_points(raw: Any, *, label: str) -> list[dict[str, float]]:
    """Validated ``horizon`` list, sorted by azimuth (azimuth wrapped to [-180, 180))."""
    where = f"{label}: {HORIZON_KEY}"
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{where} muss eine nicht leere Liste von Punkten sein.")
    points: dict[float, float] = {}
    for index, item in enumerate(raw):
        at = f"{where}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{at} muss ein Objekt mit azimuth_deg und elevation_deg sein.")
        extra = sorted(set(item) - {"azimuth_deg", "elevation_deg"})
        if extra:
            raise ValueError(f"{at} enthält unbekannte Felder {', '.join(extra)}.")
        azimuth_raw = _number(item.get("azimuth_deg"), where=f"{at}.azimuth_deg")
        if azimuth_raw < -180.0 or azimuth_raw > 180.0:
            raise ValueError(
                f"{at}.azimuth_deg muss zwischen -180 und 180 liegen (ist {azimuth_raw:g})."
            )
        elevation = _number(item.get("elevation_deg"), where=f"{at}.elevation_deg")
        if elevation < 0.0 or elevation > MAX_ELEVATION_DEG:
            raise ValueError(
                f"{at}.elevation_deg muss zwischen 0 und {MAX_ELEVATION_DEG:g} liegen "
                f"(ist {elevation:g})."
            )
        azimuth = wrap_azimuth(azimuth_raw)
        if azimuth in points:
            raise ValueError(f"{where}: Azimut {azimuth:g}° kommt mehrfach vor.")
        points[azimuth] = elevation
    return [
        {"azimuth_deg": azimuth, "elevation_deg": points[azimuth]} for azimuth in sorted(points)
    ]


def normalize_horizon_fields(raw: dict, *, label: str) -> dict[str, Any]:
    """``horizon_source`` and ``horizon`` of a raw house profile.

    Missing fields mean no horizon. ``manual`` needs the list. A list with an explicit
    ``none`` is kept but not applied (the configurator's switch is off); a list without
    ``horizon_source`` is an error, because it would be ignored silently.
    """
    source_raw = raw.get(HORIZON_SOURCE_KEY)
    points_raw = raw.get(HORIZON_KEY)
    source_given = source_raw not in (None, "")
    source = str(source_raw).strip().lower() if source_given else SOURCE_NONE
    if source not in HORIZON_SOURCES:
        raise ValueError(
            f"{label}: {HORIZON_SOURCE_KEY} muss {' oder '.join(HORIZON_SOURCES)} sein "
            f"(ist {source_raw!r})."
        )
    if points_raw is None:
        if source == SOURCE_MANUAL:
            raise ValueError(
                f"{label}: {HORIZON_SOURCE_KEY} ist '{SOURCE_MANUAL}', aber {HORIZON_KEY} fehlt."
            )
        return {HORIZON_SOURCE_KEY: SOURCE_NONE, HORIZON_KEY: None}
    if not source_given:
        raise ValueError(
            f"{label}: {HORIZON_KEY} ist gesetzt, aber {HORIZON_SOURCE_KEY} fehlt "
            f"('{SOURCE_MANUAL}' = anwenden, '{SOURCE_NONE}' = gespeichert, aber aus)."
        )
    return {
        HORIZON_SOURCE_KEY: source,
        HORIZON_KEY: normalize_horizon_points(points_raw, label=label),
    }


def stored_horizon_fields(carrier: dict | None) -> dict[str, Any]:
    """The two profile fields as stored (also a switched-off list); empty without a list."""
    if not isinstance(carrier, dict) or not carrier.get(HORIZON_KEY):
        return {}
    return {
        HORIZON_SOURCE_KEY: carrier.get(HORIZON_SOURCE_KEY, SOURCE_NONE),
        HORIZON_KEY: [dict(point) for point in carrier[HORIZON_KEY]],
    }


def horizon_from_points(points: Any) -> HorizonProfile | None:
    """Profile from a normalized point list; None when there is nothing to shade."""
    if not points:
        return None
    pairs = tuple(
        sorted((wrap_azimuth(p["azimuth_deg"]), float(p["elevation_deg"])) for p in points)
    )
    if not any(elevation > 0.0 for _azimuth, elevation in pairs):
        return None
    return HorizonProfile(points=pairs)


def horizon_from_profile(carrier: dict | None) -> HorizonProfile | None:
    """Horizon of a normalized house profile or of a ``thermal`` block carrying its fields."""
    if not isinstance(carrier, dict):
        return None
    if carrier.get(HORIZON_SOURCE_KEY, SOURCE_NONE) != SOURCE_MANUAL:
        return None
    return horizon_from_points(carrier.get(HORIZON_KEY))


def horizon_token(horizon: HorizonProfile | None) -> str:
    return horizon.token() if horizon is not None else ""


FORECAST_SOLAR_HORIZON_STEPS = 36


def forecast_solar_horizon_param(horizon: HorizonProfile) -> str:
    """forecast.solar ``horizon`` query value for a manual horizon (SUSI P3a-2).

    forecast.solar wants the elevations at equal steps, clockwise from north (north, east,
    south, west). Our azimuth is 0° = south, -90° = east, so compass bearing ``b`` is our
    azimuth ``b - 180``. 36 values (10° steps) sampled with :meth:`HorizonProfile.elevation_at`;
    whole degrees, as in forecast.solar's docs. The line **replaces** forecast.solar's own
    PVGIS terrain horizon.
    """
    step = 360.0 / FORECAST_SOLAR_HORIZON_STEPS
    values = (
        round(horizon.elevation_at(index * step - 180.0))
        for index in range(FORECAST_SOLAR_HORIZON_STEPS)
    )
    return ",".join(str(int(value)) for value in values)


def copy_horizon_fields(source: dict | None, target: dict) -> None:
    """Carry the profile's horizon into ``target`` (as latitude / longitude travel)."""
    if not isinstance(source, dict):
        return
    if source.get(HORIZON_SOURCE_KEY, SOURCE_NONE) == SOURCE_MANUAL and source.get(HORIZON_KEY):
        target[HORIZON_SOURCE_KEY] = SOURCE_MANUAL
        target[HORIZON_KEY] = [dict(point) for point in source[HORIZON_KEY]]
    else:
        target.pop(HORIZON_SOURCE_KEY, None)
        target.pop(HORIZON_KEY, None)


def sun_position(lat: float, lon: float, moment_utc: datetime) -> tuple[float, float]:
    """(elevation °, azimuth ° with 0 = south, west positive) at a UTC moment, via astral."""
    from astral import Observer
    from astral.sun import zenith_and_azimuth

    if moment_utc.tzinfo is None:
        moment_utc = moment_utc.replace(tzinfo=timezone.utc)
    zenith, azimuth_north = zenith_and_azimuth(
        Observer(latitude=lat, longitude=lon, elevation=0.0), moment_utc, with_refraction=True
    )
    return 90.0 - float(zenith), wrap_azimuth(float(azimuth_north) - 180.0)


@lru_cache(maxsize=60000)
def _hour_samples(lat: float, lon: float, stamp_utc: datetime) -> tuple[tuple[float, float], ...]:
    """Sun positions at the sub-sample moments of the hour that ends at ``stamp_utc``."""
    step = 60.0 / SUB_SAMPLES
    return tuple(
        sun_position(lat, lon, stamp_utc - timedelta(minutes=step * (index + 0.5)))
        for index in range(SUB_SAMPLES)
    )


def cos_incidence(
    sun_elevation_deg: float, sun_azimuth_deg: float, *, tilt_deg: float, azimuth_deg: float
) -> float:
    """cos of the angle between the sun and the normal of a tilted surface (may be negative)."""
    elevation = math.radians(sun_elevation_deg)
    tilt = math.radians(tilt_deg)
    return math.sin(elevation) * math.cos(tilt) + math.cos(elevation) * math.sin(tilt) * math.cos(
        math.radians(sun_azimuth_deg - azimuth_deg)
    )


def beam_blocked_factor(
    stamp_utc: datetime,
    *,
    lat: float,
    lon: float,
    tilt_deg: float,
    azimuth_deg: float,
    horizon: HorizonProfile,
) -> float:
    """Σ(blocked × max(0, cos AOI)) / n_up for the hour ending at ``stamp_utc`` (0 at night)."""
    if stamp_utc.tzinfo is not None:
        stamp_utc = stamp_utc.astimezone(timezone.utc).replace(tzinfo=None)
    samples = _hour_samples(round(float(lat), 4), round(float(lon), 4), stamp_utc)
    up = 0
    blocked = 0.0
    for elevation, azimuth in samples:
        if elevation <= 0.0:
            continue
        up += 1
        if elevation < horizon.elevation_at(azimuth):
            blocked += max(
                0.0, cos_incidence(elevation, azimuth, tilt_deg=tilt_deg, azimuth_deg=azimuth_deg)
            )
    return blocked / up if up else 0.0


def shade_tilted_wm2(
    stamps_utc: Sequence[datetime],
    tilted_wm2: Sequence[float | None],
    dni_wm2: Sequence[float | None],
    *,
    lat: float,
    lon: float,
    tilt_deg: float,
    azimuth_deg: float,
    horizon: HorizonProfile,
) -> list[float | None]:
    """Tilted irradiance with the beam removed while the sun is behind the horizon.

    A missing tilted value stays missing. A missing DNI makes the hour missing when the mask
    would need it (no guess about the beam); it does not matter while nothing is blocked.
    """
    if not (len(stamps_utc) == len(tilted_wm2) == len(dni_wm2)):
        raise ValueError(
            "Horizontmaske: Zeitstempel, Einstrahlung und DNI sind unterschiedlich lang "
            f"({len(stamps_utc)}, {len(tilted_wm2)}, {len(dni_wm2)})."
        )
    out: list[float | None] = []
    for stamp, tilted, dni in zip(stamps_utc, tilted_wm2, dni_wm2):
        if tilted is None or tilted != tilted:
            out.append(None)
            continue
        factor = beam_blocked_factor(
            stamp, lat=lat, lon=lon, tilt_deg=tilt_deg, azimuth_deg=azimuth_deg, horizon=horizon
        )
        if factor <= 0.0:
            out.append(float(tilted))
        elif dni is None or dni != dni:
            out.append(None)
        else:
            out.append(round(max(0.0, float(tilted) - float(dni) * factor), 3))
    return out


def shade_hourly_payload(
    payload: dict,
    *,
    tilted_var: str,
    dni_var: str,
    lat: float,
    lon: float,
    tilt_deg: float,
    azimuth_deg: float,
    horizon: HorizonProfile,
) -> dict:
    """Copy of a ``timezone=UTC`` Open-Meteo payload with ``tilted_var`` shaded."""
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict):
        raise ValueError("Horizontmaske: Open-Meteo-Antwort ohne hourly-Block.")
    times = hourly.get("time") or []
    tilted = hourly.get(tilted_var)
    dni = hourly.get(dni_var)
    if tilted is None or dni is None:
        missing = tilted_var if tilted is None else dni_var
        raise ValueError(f"Horizontmaske: Open-Meteo-Antwort ohne {missing}.")
    stamps = [datetime.fromisoformat(str(raw).replace("Z", "")) for raw in times]
    shaded = shade_tilted_wm2(
        stamps,
        tilted,
        dni,
        lat=lat,
        lon=lon,
        tilt_deg=tilt_deg,
        azimuth_deg=azimuth_deg,
        horizon=horizon,
    )
    return {**payload, "hourly": {**hourly, tilted_var: shaded}}


def sun_path(lat: float, lon: float, day, *, step_minutes: int = 10) -> list[tuple[float, float]]:
    """(azimuth, elevation) of the sun above 0° on a UTC day, sorted by azimuth (for the chart)."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    path = []
    for minute in range(0, 24 * 60, step_minutes):
        elevation, azimuth = sun_position(lat, lon, start + timedelta(minutes=minute))
        if elevation > 0.0:
            path.append((azimuth, elevation))
    return sorted(path)
