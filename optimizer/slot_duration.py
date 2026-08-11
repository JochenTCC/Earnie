"""MILP / planning-matrix slot length (hours).

Version 2.5.e+: matrix and MILP use quarter-hour slots (``DEFAULT_DT_H = 0.25``).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

DEFAULT_DT_H = 0.25
SLOTS_PER_HOUR = int(round(1.0 / DEFAULT_DT_H))


def validate_dt_h(dt_h: float) -> float:
    """Return ``dt_h`` if positive; raise otherwise."""
    value = float(dt_h)
    if value <= 0.0:
        raise ValueError(f"dt_h must be > 0 (got {dt_h!r})")
    return value


def slots_for_wall_hours(wall_hours: float, dt_h: float | None = None) -> int:
    """Convert wall-clock hours to a slot count (ceil)."""
    dt = validate_dt_h(DEFAULT_DT_H if dt_h is None else dt_h)
    return max(0, math.ceil(float(wall_hours) / dt))


def normalize_quarter_hour_slot(moment: datetime) -> datetime:
    """Floor ``moment`` to the start of its 15-minute slot (keeps tzinfo)."""
    minute = (moment.minute // 15) * 15
    return moment.replace(minute=minute, second=0, microsecond=0)


def floor_to_hour_slot(moment: datetime) -> datetime:
    """Floor ``moment`` to the clock hour (parent of a QH slot)."""
    return moment.replace(minute=0, second=0, microsecond=0)


def slot_step(dt_h: float | None = None) -> timedelta:
    """Timedelta for one planning/MILP slot."""
    return timedelta(hours=validate_dt_h(DEFAULT_DT_H if dt_h is None else dt_h))


def energy_kwh_from_kw(
    kw_values,
    dt_h: float | None = None,
    *,
    ndigits: int = 3,
) -> float:
    """Convert a sequence of average slot powers (kW) to energy (kWh)."""
    dt = validate_dt_h(DEFAULT_DT_H if dt_h is None else dt_h)
    total = sum(float(value or 0.0) for value in kw_values) * dt
    return round(total, ndigits)
