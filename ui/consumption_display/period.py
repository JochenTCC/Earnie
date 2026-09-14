"""Shared time-window primitives for Analyse, SE, and HK period navigation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum

from ui.consumption_validation_charts import format_iso_week_label, iso_weeks_in_series


class PeriodKind(str, Enum):
    ROLLING_7 = "rolling_7"
    ROLLING_28 = "rolling_28"
    ISO_WEEK = "iso_week"
    # Reserved for a later Analyse / SE chart mode — not wired in UI yet.
    ROLLING_365 = "rolling_365"


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime
    kind: PeriodKind
    iso_year: int | None = None
    iso_week: int | None = None


_ROLLING_DAYS: dict[PeriodKind, int] = {
    PeriodKind.ROLLING_7: 7,
    PeriodKind.ROLLING_28: 28,
    PeriodKind.ROLLING_365: 365,
}


def parse_period_timestamp(ts_raw: str) -> datetime:
    """Parse ISO-ish timestamp strings; preserve tzinfo when the string has an offset."""
    return datetime.fromisoformat(ts_raw.replace(" ", "T", 1))


def rolling_days(kind: PeriodKind) -> int:
    """Day length for rolling kinds; raises for ISO_WEEK."""
    days = _ROLLING_DAYS.get(kind)
    if days is None:
        raise ValueError(f"PeriodKind {kind} is not a rolling window.")
    return days


def _kind_for_days(days: int) -> PeriodKind:
    if days == 7:
        return PeriodKind.ROLLING_7
    if days == 28:
        return PeriodKind.ROLLING_28
    if days == 365:
        return PeriodKind.ROLLING_365
    if days <= 7:
        return PeriodKind.ROLLING_7
    if days <= 28:
        return PeriodKind.ROLLING_28
    return PeriodKind.ROLLING_365


def resolve_rolling_window(anchor_end: datetime, *, days: int) -> TimeWindow:
    """Inclusive window ``[anchor_end - days, anchor_end]`` on both ends.

    Slots with ``start <= ts <= end`` belong to the window. ``days`` must be > 0.
    """
    if days <= 0:
        raise ValueError(f"days must be > 0, got {days}.")
    start = anchor_end - timedelta(days=days)
    return TimeWindow(start=start, end=anchor_end, kind=_kind_for_days(days))


def resolve_rolling_kind_window(anchor_end: datetime, kind: PeriodKind) -> TimeWindow:
    return resolve_rolling_window(anchor_end, days=rolling_days(kind))


def timestamp_in_window(ts: datetime, window: TimeWindow) -> bool:
    if window.kind == PeriodKind.ISO_WEEK and window.iso_year is not None:
        return ts.isocalendar()[:2] == (window.iso_year, window.iso_week)
    return window.start <= ts <= window.end


def indices_in_window(timestamps: list[str], window: TimeWindow) -> list[int]:
    return [
        index
        for index, ts_raw in enumerate(timestamps)
        if timestamp_in_window(parse_period_timestamp(ts_raw), window)
    ]


def format_window_label(window: TimeWindow) -> str:
    if (
        window.kind == PeriodKind.ISO_WEEK
        and window.iso_year is not None
        and window.iso_week is not None
    ):
        return format_iso_week_label(window.iso_year, window.iso_week)
    days = max(1, int(round((window.end - window.start).total_seconds() / 86400)))
    start_s = window.start.strftime("%d.%m.%Y")
    end_s = window.end.strftime("%d.%m.%Y")
    return f"{start_s}–{end_s} ({days} Tage)"


def _filtered_datetimes(
    timestamps: list[str],
    *,
    nav_bounds: tuple[datetime, datetime] | None,
) -> list[datetime]:
    values: list[datetime] = []
    for ts_raw in timestamps:
        ts = parse_period_timestamp(ts_raw)
        if nav_bounds is not None and (ts < nav_bounds[0] or ts > nav_bounds[1]):
            continue
        values.append(ts)
    return values


def list_rolling_windows(
    timestamps: list[str],
    *,
    days: int,
    nav_bounds: tuple[datetime, datetime] | None = None,
) -> list[TimeWindow]:
    """Discrete rolling windows stepped by ``days``; oldest first, newest last."""
    points = _filtered_datetimes(timestamps, nav_bounds=nav_bounds)
    if not points or days <= 0:
        return []
    data_min = min(points)
    anchor = max(points)
    collected: list[TimeWindow] = []
    while True:
        window = resolve_rolling_window(anchor, days=days)
        if any(timestamp_in_window(ts, window) for ts in points):
            collected.append(window)
        if window.start <= data_min:
            break
        next_anchor = anchor - timedelta(days=days)
        if next_anchor >= anchor:
            break
        anchor = next_anchor
    collected.reverse()
    return _dedupe_windows(collected)


def list_rolling_windows_for_kind(
    timestamps: list[str],
    kind: PeriodKind,
    *,
    nav_bounds: tuple[datetime, datetime] | None = None,
) -> list[TimeWindow]:
    return list_rolling_windows(
        timestamps, days=rolling_days(kind), nav_bounds=nav_bounds
    )


def iso_week_time_window(iso_year: int, iso_week: int) -> TimeWindow:
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    sunday = date.fromisocalendar(iso_year, iso_week, 7)
    return TimeWindow(
        start=datetime.combine(monday, time.min),
        end=datetime.combine(sunday, time.max.replace(microsecond=0)),
        kind=PeriodKind.ISO_WEEK,
        iso_year=iso_year,
        iso_week=iso_week,
    )


def list_iso_week_windows(
    timestamps: list[str],
    *,
    nav_bounds: tuple[datetime, datetime] | None = None,
) -> list[TimeWindow]:
    if nav_bounds is None:
        series = [(ts, 0.0) for ts in timestamps]
    else:
        series = [
            (ts, 0.0)
            for ts in timestamps
            if nav_bounds[0] <= parse_period_timestamp(ts) <= nav_bounds[1]
        ]
    weeks = iso_weeks_in_series(series)
    return [iso_week_time_window(year, week) for year, week in weeks]


def list_windows_for_kind(
    timestamps: list[str],
    kind: PeriodKind,
    *,
    nav_bounds: tuple[datetime, datetime] | None = None,
) -> list[TimeWindow]:
    if kind == PeriodKind.ISO_WEEK:
        return list_iso_week_windows(timestamps, nav_bounds=nav_bounds)
    return list_rolling_windows_for_kind(timestamps, kind, nav_bounds=nav_bounds)


def window_containing_date(
    windows: list[TimeWindow],
    day: date,
) -> TimeWindow | None:
    for window in windows:
        if window.start.date() <= day <= window.end.date():
            return window
    return None


def _dedupe_windows(windows: list[TimeWindow]) -> list[TimeWindow]:
    seen: set[tuple[datetime, datetime, PeriodKind]] = set()
    unique: list[TimeWindow] = []
    for window in windows:
        key = (window.start, window.end, window.kind)
        if key in seen:
            continue
        seen.add(key)
        unique.append(window)
    return unique
