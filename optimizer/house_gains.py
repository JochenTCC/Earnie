"""SUSI P2 — hourly solar and internal gains of the house RC (kW, heat into the heated volume).

Solar: four vertical window surfaces (S/E/W/N, tilt 90°) from the Open-Meteo bundle,
``gain = Σ window_area × g × frame_shading × irradiance``. Internal: the modeled consumers'
hourly electric kW × their ``internal_gain_factor`` plus the Grundlast × the profile factor.
The Grundlast depends on the heating consumer's own electric draw (annual_kwh minus all modeled
consumers), so the year model solves it as a fixed point together with the H calibration
(``optimizer.thermal_house``).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from data.open_meteo_solar_archive import TiltedSurface
from house_config.house_gains import (
    INTERNAL_GAIN_FACTOR_KEY,
    SOLAR_GAINS_KEY,
    WINDOW_DIRECTIONS,
    solar_gains_active,
)

# Open-Meteo azimuth: 0° south, -90° east, 90° west, 180° north.
WINDOW_AZIMUTH_DEG: dict[str, float] = {"s": 0.0, "e": -90.0, "w": 90.0, "n": 180.0}
WINDOW_TILT_DEG = 90.0
HOURS_PER_YEAR = 8760


def window_surface(direction: str) -> TiltedSurface:
    return TiltedSurface(tilt_deg=WINDOW_TILT_DEG, azimuth_deg=WINDOW_AZIMUTH_DEG[direction])


def window_surfaces_for_thermal(thermal: dict[str, Any]) -> list[TiltedSurface]:
    """Vertical surfaces the climate bundle must carry (empty when solar gains are off)."""
    if not solar_gains_active(thermal):
        return []
    areas = thermal[SOLAR_GAINS_KEY]["window_area_m2"]
    return [window_surface(d) for d in WINDOW_DIRECTIONS if float(areas[d]) > 0.0]


def solar_gain_kw_series(bundle, thermal: dict[str, Any]) -> pd.Series | None:
    """Hourly solar gain (kW) through the windows from a climate bundle; None when off."""
    if not solar_gains_active(thermal):
        return None
    block = thermal[SOLAR_GAINS_KEY]
    factor = float(block["g_value"]) * float(block["frame_shading_factor"]) / 1000.0
    total: pd.Series | None = None
    for direction in WINDOW_DIRECTIONS:
        area = float(block["window_area_m2"][direction])
        if area <= 0.0:
            continue
        series = bundle.collector_surface_series(window_surface(direction))
        part = series.fillna(0.0).clip(lower=0.0) * (area * factor)
        total = part if total is None else total.add(part, fill_value=0.0)
    return total


def thermal_bundle_surfaces(thermal: dict[str, Any], collector: TiltedSurface | None) -> list:
    """Collector (when given) plus the window surfaces for one thermal block."""
    surfaces = [collector] if collector is not None else []
    return surfaces + window_surfaces_for_thermal(thermal)


def thermal_climate_kwargs(
    bundle,
    thermal: dict[str, Any],
    collector: TiltedSurface | None,
) -> dict[str, Any]:
    """Climate keyword arguments of the year model from one Open-Meteo bundle."""
    area_m2 = float(thermal.get("solar_thermal_area_m2", 0.0) or 0.0)
    hourly_wm2 = (
        bundle.collector_surface_series(collector)
        if area_m2 > 0.0 and collector is not None
        else None
    )
    return {
        "hourly_temperature_c": bundle.temperature_c,
        "hourly_collector_wm2": hourly_wm2,
        "hourly_solar_gain_kw": solar_gain_kw_series(bundle, thermal),
    }


def _gain_consumers(internal_gains: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((internal_gains or {}).get("consumers") or [])


def other_consumers_annual_kwh(internal_gains: dict[str, Any] | None) -> float:
    """Σ annual kWh of the other modeled consumers (Grundlast subtracts them)."""
    from house_config.baseload import consumer_annual_kwh

    return float(sum(consumer_annual_kwh(c) for c in _gain_consumers(internal_gains)))


def consumer_gain_kw(internal_gains: dict[str, Any] | None, *, hours: int) -> list[float]:
    """Σ hourly kW × internal_gain_factor of the other consumers (factor 0 skipped)."""
    from data.consumption_profiles import _modeled_consumer_hourly_kw

    total = [0.0] * hours
    for consumer in _gain_consumers(internal_gains):
        factor = float(consumer.get(INTERNAL_GAIN_FACTOR_KEY, 0.0) or 0.0)
        if factor <= 0.0:
            continue
        series = _modeled_consumer_hourly_kw(consumer, hours=min(hours, HOURS_PER_YEAR))
        for hour in range(hours):
            total[hour] += factor * float(series[hour % len(series)])
    return total


def baseload_gain_kw(
    internal_gains: dict[str, Any] | None,
    *,
    others_kwh: float,
    own_electric_kwh: float,
) -> float:
    """Constant Grundlast gain (kW): factor × max(2 % floor, annual − others − own) / 8760.

    Same rule as ``house_config.baseload.compute_baseload_kwh``; ``own_electric_kwh`` is the
    heating consumer's electric draw (0 for a fuel heat source).
    """
    from house_config.baseload import BASELOAD_MIN_FRACTION

    if not internal_gains:
        return 0.0
    factor = float(internal_gains.get("baseload_factor", 0.0) or 0.0)
    annual = float(internal_gains.get("annual_kwh", 0.0) or 0.0)
    if factor <= 0.0 or annual <= 0.0:
        return 0.0
    baseload = max(annual * BASELOAD_MIN_FRACTION, annual - others_kwh - own_electric_kwh)
    return factor * baseload / HOURS_PER_YEAR


def aligned_hourly(series, hours: int) -> list[float]:
    """Series → float list of ``hours`` values (NaN → 0, cycled when shorter)."""
    if series is None:
        return [0.0] * hours
    values = [0.0 if pd.isna(v) else float(v) for v in list(series)]
    if not values:
        return [0.0] * hours
    return [values[i % len(values)] for i in range(hours)]
