"""
history_timeline.py – 24h-Historie aus optimization_history.jsonl (96 Viertelstunden-Slots).

Rekonstruiert das tatsächliche Produktiv-Verhalten. S-2-Charts (`build_chart_history`): fehlende Slots leer.
96h-Archiv (`build_history_timeline`): Hold-Forward für SoC/Preis.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import config
from optimizer.schedule import QUARTER_HOUR_MINUTES, quarter_hour_slot_start
from optimizer.simulation import calculate_step_cost_euro_from_row, flexible_consumer_power_kw

from . import optimization_history
from .history_chart_rows import (
    CHART_IST_BATTERY_KW_COLUMN,
    PV_IST_COLUMN,
    SLOT_HELD,
    SLOT_MISSING,
    SLOT_PRESENT,
    _build_rows_for_slot_starts,
    _chart_battery_kw_from_snapshot,
    _coerce_slot_start,
    _consumer_kw_from_entry,
    _empty_chart_row,
    _flex_dict_has_consumer,
    _format_slot_time,
    _hold_forward_row,
    _import_price_cent_from_entry,
    _index_entries_by_slot,
    _missing_chart_row,
    _parse_completed_at,
    _power_kw_from_entry,
    _zero_flex_power,
    entry_to_chart_row,
)

SLOTS_PER_DAY = 96
SLOT_DURATION_HOURS = QUARTER_HOUR_MINUTES / 60.0


@dataclass(frozen=True)
class ChartHistoryResult:
    """15-Min-Slots aus dem Produktiv-Log für ein beliebiges Chart-Fenster."""

    rows: list[dict[str, Any]]
    slot_starts: tuple[datetime, ...]
    slot_qualities: tuple[str, ...]
    slot_costs_euro: list[float]
    cumulative_costs_euro: list[float]
    slot_consumption_kwh: list[float]
    cumulative_consumption_kwh: list[float]
    present_slot_count: int
    held_slot_count: int
    missing_slot_count: int
    window_start: datetime
    window_end_exclusive: datetime
    slot_deviation_events: tuple[tuple[Any, ...], ...] = ()
    # Plan costs/savings from each hour's savings_snapshot[0] (for Chart 2 Ersparnis bisher)
    slot_planned_matched_cost_euro: tuple[float, ...] = ()
    slot_planned_optimized_cost_euro: tuple[float, ...] = ()
    slot_planned_savings_euro: tuple[float, ...] = ()


@dataclass(frozen=True)
class HistoryTimelineResult:
    """96 Viertelstunden-Slots eines vergangenen 24h-Fensters."""

    rows: list[dict[str, Any]]
    slot_costs_euro: list[float]
    cumulative_costs_euro: list[float]
    slot_consumption_kwh: list[float]
    cumulative_consumption_kwh: list[float]
    projected_savings_cumulative_euro: list[float]
    projected_savings_available: bool
    latest_projected_savings_euro: float | None
    present_slot_count: int
    held_slot_count: int
    missing_slot_count: int
    slot_qualities: tuple[str, ...]
    window_start: datetime
    window_end: datetime
    anchor_slot: datetime
    offset_days: int


def live_anchor_slot(now: datetime | None = None) -> datetime:
    """Anker wie im Live-Modus: Beginn des aktuellen Viertelstunden-Slots."""
    return quarter_hour_slot_start(now)


def history_window_bounds(
    offset_days: int,
    now: datetime | None = None,
) -> tuple[datetime, datetime, datetime]:
    """
    Grenzen für einen Historie-Schritt.

    offset_days=1 → [Anker−24h, Anker); Anker = aktueller Live-Slot-Start.
    """
    if offset_days < 1:
        raise ValueError(
            f"offset_days muss >= 1 sein (0 = Live-Modus), erhalten: {offset_days}"
        )
    anchor = live_anchor_slot(now)
    window_end = anchor - timedelta(days=offset_days - 1)
    window_start = window_end - timedelta(days=1)
    return window_start, window_end, anchor


def max_history_offset_days(now: datetime | None = None) -> int:
    """Maximale Anzahl 24h-Schritte zurück (solange Fensterstart >= frühestem Eintrag)."""
    earliest = optimization_history.earliest_replay_completed_at()
    if earliest is None:
        return 0
    anchor = live_anchor_slot(now)
    earliest_slot = quarter_hour_slot_start(earliest)
    offset = 0
    while True:
        next_offset = offset + 1
        window_start, _, _ = history_window_bounds(next_offset, now)
        if window_start < earliest_slot:
            break
        offset = next_offset
    return offset


def _slot_starts(window_start: datetime) -> list[datetime]:
    step = timedelta(minutes=QUARTER_HOUR_MINUTES)
    return [window_start + step * index for index in range(SLOTS_PER_DAY)]


def quarter_hour_slots_between(
    window_start: datetime,
    window_end_exclusive: datetime,
) -> tuple[datetime, ...]:
    """Viertelstunden-Slots in [window_start, window_end_exclusive)."""
    if window_start.tzinfo is None or window_end_exclusive.tzinfo is None:
        raise ValueError("window_start und window_end_exclusive müssen timezone-aware sein.")
    if window_end_exclusive <= window_start:
        return ()
    step = timedelta(minutes=QUARTER_HOUR_MINUTES)
    slot = _coerce_slot_start(window_start)
    end_bound = _coerce_slot_start(window_end_exclusive)
    if window_end_exclusive > end_bound:
        end_bound += step
    slots: list[datetime] = []
    while slot < end_bound and slot < window_end_exclusive:
        slots.append(slot)
        slot += step
    return tuple(slots)


def _slot_cost_euro(row: dict[str, Any], sell_price_cent: float) -> float:
    hourly = calculate_step_cost_euro_from_row(row, sell_price_cent)
    return round(hourly * SLOT_DURATION_HOURS, 6)


def _slot_consumption_kwh(row: dict[str, Any]) -> float:
    power = float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0) + flexible_consumer_power_kw(row)
    return round(power * SLOT_DURATION_HOURS, 6)


def _cumulative(values: list[float]) -> list[float]:
    total = 0.0
    result: list[float] = []
    for value in values:
        total += value
        result.append(round(total, 4))
    return result


def _entry_savings_snapshot(entry: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = entry.get("savings_snapshot")
    if not isinstance(snapshot, dict):
        return None
    if not snapshot.get("hourly_savings_euro"):
        return None
    return snapshot


def _snapshot_entry_for_hour(
    by_slot: dict[datetime, dict[str, Any]],
    hour_start: datetime,
) -> dict[str, Any] | None:
    """Last log entry in ``hour_start``..+1h that carries a savings_snapshot."""
    step = timedelta(minutes=QUARTER_HOUR_MINUTES)
    entry = None
    for quarter in range(4):
        slot = hour_start + step * quarter
        candidate = by_slot.get(_coerce_slot_start(slot))
        if candidate is not None and _entry_savings_snapshot(candidate) is not None:
            entry = candidate
    return entry


def _slot_plan_increments_from_snapshots(
    by_slot: dict[datetime, dict[str, Any]],
    slot_starts: list[datetime] | tuple[datetime, ...],
    snapshot_key: str,
) -> tuple[float, ...]:
    """Spread savings_snapshot[key][0] of each clock-hour across that hour's slots."""
    from collections import defaultdict

    from data.planning_window import normalize_hour_slot

    hour_indices: dict[datetime, list[int]] = defaultdict(list)
    for index, slot in enumerate(slot_starts):
        hour_indices[normalize_hour_slot(slot)].append(index)
    out = [0.0] * len(slot_starts)
    for hour_start, indices in hour_indices.items():
        entry = _snapshot_entry_for_hour(by_slot, hour_start)
        if entry is None:
            continue
        snapshot = _entry_savings_snapshot(entry)
        assert snapshot is not None
        values = snapshot.get(snapshot_key) or []
        hourly = float(values[0]) if values else 0.0
        share = hourly / len(indices)
        for index in indices:
            out[index] = share
    return tuple(out)


def _projected_hourly_savings_from_slots(
    by_slot: dict[datetime, dict[str, Any]],
    slot_starts: list[datetime],
) -> list[float]:
    """
    Pro Clock-Stunde: Stunden-Ersparnis aus dem letzten Lauf dieser Stunde.

    Verwendet hourly_savings_euro[0] (Ersparnis für die laufende Stunde).
    Fehlende Stunden werden mit 0.0 befüllt.
    """
    hours = len(slot_starts) // 4
    hourly: list[float] = []
    for hour in range(hours):
        hour_start = slot_starts[hour * 4]
        entry = _snapshot_entry_for_hour(by_slot, hour_start)
        if entry is None:
            hourly.append(0.0)
            continue
        snapshot = _entry_savings_snapshot(entry)
        assert snapshot is not None
        values = snapshot.get("hourly_savings_euro") or []
        hourly.append(float(values[0]) if values else 0.0)
    return hourly


def _hourly_to_slot_cumulative(hourly: list[float], slot_count: int) -> list[float]:
    """Kumulierte Stunden-Ersparnis auf Viertelstunden-Slots (HV-Linie)."""
    if not hourly:
        return [0.0] * slot_count
    hourly_cum: list[float] = []
    total = 0.0
    for value in hourly:
        total += float(value)
        hourly_cum.append(round(total, 4))
    slot_values: list[float] = []
    for hour_total in hourly_cum:
        slot_values.extend([hour_total] * 4)
    if len(slot_values) < slot_count:
        slot_values.extend([slot_values[-1] if slot_values else 0.0] * (slot_count - len(slot_values)))
    return slot_values[:slot_count]


def _latest_projected_savings_euro(
    by_slot: dict[datetime, dict[str, Any]],
) -> float | None:
    latest_at: datetime | None = None
    latest_value: float | None = None
    for completed, entry in (
        (_parse_completed_at(entry), entry)
        for entry in by_slot.values()
    ):
        if completed is None:
            continue
        snapshot = _entry_savings_snapshot(entry)
        if snapshot is None:
            continue
        if latest_at is None or completed > latest_at:
            latest_at = completed
            latest_value = float(snapshot.get("savings_matched_euro", 0.0))
    return latest_value


def _projected_savings_available(by_slot: dict[datetime, dict[str, Any]]) -> bool:
    return any(_entry_savings_snapshot(entry) is not None for entry in by_slot.values())


def _empty_chart_history(
    window_start: datetime,
    window_end_exclusive: datetime,
) -> ChartHistoryResult:
    return ChartHistoryResult(
        rows=[],
        slot_starts=(),
        slot_qualities=(),
        slot_costs_euro=[],
        cumulative_costs_euro=[],
        slot_consumption_kwh=[],
        cumulative_consumption_kwh=[],
        present_slot_count=0,
        held_slot_count=0,
        missing_slot_count=0,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        slot_deviation_events=(),
    )


def _chart_history_cost_metrics(
    rows: list[dict[str, Any]],
    qualities: tuple[str, ...],
    by_slot: dict,
    slot_starts: tuple[datetime, ...],
) -> tuple[list[float], list[float], tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    sell_price_cent = config.get_push_price_cent()
    slot_costs = [
        0.0 if quality == SLOT_MISSING else _slot_cost_euro(row, sell_price_cent)
        for row, quality in zip(rows, qualities)
    ]
    slot_kwh = [
        0.0 if quality == SLOT_MISSING else _slot_consumption_kwh(row)
        for row, quality in zip(rows, qualities)
    ]
    planned_matched = _slot_plan_increments_from_snapshots(
        by_slot, slot_starts, "hourly_matched_baseline_cost_euro"
    )
    planned_optimized = _slot_plan_increments_from_snapshots(
        by_slot, slot_starts, "hourly_optimized_cost_euro"
    )
    planned_savings = _slot_plan_increments_from_snapshots(
        by_slot, slot_starts, "hourly_savings_euro"
    )
    return slot_costs, slot_kwh, planned_matched, planned_optimized, planned_savings


def build_chart_history(
    window_start: datetime,
    window_end_exclusive: datetime,
) -> ChartHistoryResult:
    """
    Rekonstruiert 15-Min-Ist-Daten für [window_start, window_end_exclusive).

    Fensterende exklusiv = history_boundary_exclusive(now) (Spec ui-sunset2sunset v0.6 §6).
    """
    if window_start.tzinfo is None or window_end_exclusive.tzinfo is None:
        raise ValueError("window_start und window_end_exclusive müssen timezone-aware sein.")
    if window_end_exclusive <= window_start:
        return _empty_chart_history(window_start, window_end_exclusive)
    slot_starts = quarter_hour_slots_between(window_start, window_end_exclusive)
    rows, qualities, present, held, missing, by_slot, closed_by = (
        _build_rows_for_slot_starts(
            slot_starts,
            include_date=True,
            hold_forward=False,
        )
    )
    from optimizer.deviation_timeline import build_slot_deviation_series

    deviation_events = build_slot_deviation_series(
        by_slot,
        slot_starts,
        qualities,
        closed_by_interval=closed_by,
    )
    slot_costs, slot_kwh, planned_matched, planned_optimized, planned_savings = (
        _chart_history_cost_metrics(rows, qualities, by_slot, slot_starts)
    )
    return ChartHistoryResult(
        rows=rows,
        slot_starts=slot_starts,
        slot_qualities=qualities,
        slot_costs_euro=slot_costs,
        cumulative_costs_euro=_cumulative(slot_costs),
        slot_consumption_kwh=slot_kwh,
        cumulative_consumption_kwh=_cumulative(slot_kwh),
        present_slot_count=present,
        held_slot_count=held,
        missing_slot_count=missing,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        slot_deviation_events=deviation_events,
        slot_planned_matched_cost_euro=planned_matched,
        slot_planned_optimized_cost_euro=planned_optimized,
        slot_planned_savings_euro=planned_savings,
    )


def build_history_timeline(
    offset_days: int,
    now: datetime | None = None,
) -> HistoryTimelineResult:
    """
    Rekonstruiert 96 Viertelstunden-Slots für ein vergangenes 24h-Fenster.

    Fehlende Slots: Hold-Forward des letzten bekannten Werts (Preis/SoC; Flex = 0 kW).
    """
    window_start, window_end, anchor = history_window_bounds(offset_days, now)
    slot_starts = _slot_starts(window_start)
    rows, qualities, present, held, missing, _by_slot, _closed_by = (
        _build_rows_for_slot_starts(slot_starts)
    )
    entries = optimization_history.load_replay_entries_between(window_start, window_end)
    by_slot = _index_entries_by_slot(entries)
    sell_price_cent = config.get_push_price_cent()

    slot_costs = [_slot_cost_euro(row, sell_price_cent) for row in rows]
    slot_kwh = [_slot_consumption_kwh(row) for row in rows]
    projected_hourly = _projected_hourly_savings_from_slots(by_slot, slot_starts)
    projected_savings_cum = _hourly_to_slot_cumulative(projected_hourly, len(slot_starts))
    savings_available = _projected_savings_available(by_slot)

    return HistoryTimelineResult(
        rows=rows,
        slot_costs_euro=slot_costs,
        cumulative_costs_euro=_cumulative(slot_costs),
        slot_consumption_kwh=slot_kwh,
        cumulative_consumption_kwh=_cumulative(slot_kwh),
        projected_savings_cumulative_euro=projected_savings_cum,
        projected_savings_available=savings_available,
        latest_projected_savings_euro=_latest_projected_savings_euro(by_slot),
        present_slot_count=present,
        held_slot_count=held,
        missing_slot_count=missing,
        slot_qualities=qualities,
        window_start=window_start,
        window_end=window_end,
        anchor_slot=anchor,
        offset_days=offset_days,
    )


def format_gap_notice(result: HistoryTimelineResult) -> str | None:
    """Hinweistext für fehlende oder gehaltene Slots (Spezifikation B+C)."""
    parts: list[str] = []
    if result.missing_slot_count:
        parts.append(f"{result.missing_slot_count} von {SLOTS_PER_DAY} Slots ohne Daten")
    if result.held_slot_count:
        parts.append(f"{result.held_slot_count} Slots mit letztem bekannten Wert aufgefüllt")
    if not parts:
        return None
    return " · ".join(parts)


__all__ = [
    "CHART_IST_BATTERY_KW_COLUMN",
    "ChartHistoryResult",
    "HistoryTimelineResult",
    "PV_IST_COLUMN",
    "SLOT_DURATION_HOURS",
    "SLOT_HELD",
    "SLOT_MISSING",
    "SLOT_PRESENT",
    "SLOTS_PER_DAY",
    "_build_rows_for_slot_starts",
    "_chart_battery_kw_from_snapshot",
    "_coerce_slot_start",
    "_consumer_kw_from_entry",
    "_empty_chart_row",
    "_flex_dict_has_consumer",
    "_format_slot_time",
    "_hold_forward_row",
    "_import_price_cent_from_entry",
    "_index_entries_by_slot",
    "_missing_chart_row",
    "_parse_completed_at",
    "_power_kw_from_entry",
    "_zero_flex_power",
    "build_chart_history",
    "build_history_timeline",
    "entry_to_chart_row",
    "format_gap_notice",
    "history_window_bounds",
    "live_anchor_slot",
    "max_history_offset_days",
    "quarter_hour_slots_between",
]
