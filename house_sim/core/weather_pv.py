"""Derive PV kW from weather cloud cover and sun elevation (pure function)."""
from __future__ import annotations

import math


def pv_kw_from_weather(
    pv_kwp: float,
    cloud_coverage_pct: float,
    elevation_deg: float,
) -> float:
    """Scale clear-sky sin(elevation) by cloud cover.

    Full cloud reduces output by up to 75%. Below-horizon sun → 0 kW.
    """
    kwp = float(pv_kwp)
    if kwp < 0:
        raise ValueError("pv_kwp must be >= 0")
    elev = float(elevation_deg)
    if elev <= 0.0:
        return 0.0
    cloud = max(0.0, min(100.0, float(cloud_coverage_pct))) / 100.0
    clear = kwp * math.sin(math.radians(elev))
    return max(0.0, clear * (1.0 - 0.75 * cloud))
