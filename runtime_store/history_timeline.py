"""
history_timeline.py – Ist-Historie aus optimization_history.jsonl (Viertelstunden-Slots).

Rekonstruiert das tatsächliche Produktiv-Verhalten für ein Chart-Fenster
(`build_chart_history`): fehlende Slots bleiben leer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import config
from optimizer.schedule import QUARTER_HOUR_MINUTES
from optimizer.simulation import calculate_step_cost_euro_from_row, flexible_consumer_power_kw
from optimizer.slot_duration import quarter_hour_grid

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
    _import_price_cent_from_entry,
    _index_entries_by_slot,
    _missing_chart_row,
    _parse_completed_at,
    _power_kw_from_entry,
    _zero_flex_power,
    entry_to_chart_row,
)

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


def quarter_hour_slots_between(
    window_start: datetime,
    window_end_exclusive: datetime,
) -> tuple[datetime, ...]:
    """Viertelstunden-Slots in [window_start, window_end_exclusive), in Echtzeit gestuft (DST: 92 / 100)."""
    if window_start.tzinfo is None or window_end_exclusive.tzinfo is None:
        raise ValueError("window_start und window_end_exclusive müssen timezone-aware sein.")
    if window_end_exclusive <= window_start:
        return ()
    slots = quarter_hour_grid(
        _coerce_slot_start(window_start),
        window_end_exclusive,
        step=timedelta(minutes=QUARTER_HOUR_MINUTES),
        include_end=False,
    )
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
) -> tuple[list[float], list[float]]:
    sell_price_cent = config.get_push_price_cent()
    slot_costs = [
        0.0 if quality == SLOT_MISSING else _slot_cost_euro(row, sell_price_cent)
        for row, quality in zip(rows, qualities)
    ]
    slot_kwh = [
        0.0 if quality == SLOT_MISSING else _slot_consumption_kwh(row)
        for row, quality in zip(rows, qualities)
    ]
    return slot_costs, slot_kwh


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
        )
    )
    from optimizer.deviation_timeline import build_slot_deviation_series

    deviation_events = build_slot_deviation_series(
        by_slot,
        slot_starts,
        qualities,
        closed_by_interval=closed_by,
    )
    slot_costs, slot_kwh = _chart_history_cost_metrics(rows, qualities)
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
    )


__all__ = [
    "CHART_IST_BATTERY_KW_COLUMN",
    "ChartHistoryResult",
    "PV_IST_COLUMN",
    "SLOT_DURATION_HOURS",
    "SLOT_HELD",
    "SLOT_MISSING",
    "SLOT_PRESENT",
    "_build_rows_for_slot_starts",
    "_chart_battery_kw_from_snapshot",
    "_coerce_slot_start",
    "_consumer_kw_from_entry",
    "_empty_chart_row",
    "_flex_dict_has_consumer",
    "_format_slot_time",
    "_import_price_cent_from_entry",
    "_index_entries_by_slot",
    "_missing_chart_row",
    "_parse_completed_at",
    "_power_kw_from_entry",
    "_zero_flex_power",
    "build_chart_history",
    "entry_to_chart_row",
    "quarter_hour_slots_between",
]
