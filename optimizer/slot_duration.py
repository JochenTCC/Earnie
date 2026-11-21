"""MILP / planning-matrix slot length (hours).

Version 2.5.e+: matrix and MILP use quarter-hour slots (``DEFAULT_DT_H = 0.25``).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

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


def wall_hours_from_slots(n_slots: int, dt_h: float | None = None) -> int:
    """Convert a slot count to whole wall-clock hours (floor)."""
    dt = validate_dt_h(DEFAULT_DT_H if dt_h is None else dt_h)
    return int(n_slots * dt)


def normalize_quarter_hour_slot(moment: datetime) -> datetime:
    """Floor ``moment`` to the start of its 15-minute slot (keeps tzinfo)."""
    minute = (moment.minute // 15) * 15
    return moment.replace(minute=minute, second=0, microsecond=0)


def floor_to_hour_slot(moment: datetime) -> datetime:
    """Floor ``moment`` to the clock hour (parent of a QH slot)."""
    return moment.replace(minute=0, second=0, microsecond=0)


def slot_zone(moment: datetime) -> tzinfo:
    """Zone whose local time the slots of ``moment`` show.

    A ``ZoneInfo`` tzinfo is that zone; any other tzinfo (UTC, a fixed offset from an earlier
    slot) means the planning timezone from the config.
    """
    if moment.tzinfo is None:
        raise ValueError(f"Slot-Zeitpunkt {moment} muss timezone-aware sein.")
    if isinstance(moment.tzinfo, ZoneInfo):
        return moment.tzinfo
    import config

    return ZoneInfo(config.get_planning_timezone())


def fixed_offset_local(moment: datetime, zone: tzinfo) -> datetime:
    """``moment`` in the local time of ``zone`` with a fixed-offset tzinfo.

    Slot keys use this form: hour and minute are the local wall clock, while the two
    occurrences of the repeated autumn hour stay distinct (a ``ZoneInfo`` datetime ignores
    ``fold`` in comparisons and hashing) and ``+ timedelta`` is exact.
    """
    local = moment.astimezone(zone)
    return local.replace(tzinfo=timezone(local.utcoffset()))


def quarter_hour_grid(
    start: datetime,
    end: datetime,
    *,
    step: timedelta,
    include_end: bool,
    zone: tzinfo | None = None,
) -> list[datetime]:
    """Slot starts from ``start`` to ``end``, stepped in real time across DST changes.

    ``start`` must lie on the grid. Each slot carries the fixed offset of ``zone`` at its
    instant (``fixed_offset_local``), so a spring DST day has 92 and an autumn one 100
    quarter-hour slots.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start und end müssen timezone-aware sein.")
    target_zone = zone if zone is not None else slot_zone(start)
    moment = start.astimezone(timezone.utc)
    stop = end.astimezone(timezone.utc)
    slots: list[datetime] = []
    while moment < stop or (include_end and moment == stop):
        slots.append(fixed_offset_local(moment, target_zone))
        moment += step
    return slots


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
