"""SA-day cost KPI totals and plan-based achieved-savings series for Chart 2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from data.planning_window import UiChartWindow


@dataclass(frozen=True)
class DayCostTotals:
    """BL/Optimiert/Ersparnis for one sunrise→sunrise day in the visible window.

    When ``show_split_savings`` is True (running day with gray history), annotations
    show both achieved (SA→now) and expected full-day savings (through day end).
    """

    label: str
    matched_baseline_cost_euro: float
    optimized_cost_euro: float
    achieved_matched_cost_euro: float | None = None
    achieved_optimized_cost_euro: float | None = None
    show_split_savings: bool = False

    @property
    def savings_euro(self) -> float:
        return self.optimized_cost_euro - self.matched_baseline_cost_euro

    @property
    def achieved_savings_euro(self) -> float | None:
        if (
            self.achieved_matched_cost_euro is None
            or self.achieved_optimized_cost_euro is None
        ):
            return None
        return self.achieved_optimized_cost_euro - self.achieved_matched_cost_euro


def _day_label(day_start: datetime, segment_tag: str) -> str:
    return f"{segment_tag} · {day_start.strftime('%d.%m.')}"


def _slot_day_index(
    slot: datetime,
    sa0: datetime,
    sa1: datetime,
    sa2: datetime,
) -> int | None:
    if sa0 <= slot < sa1:
        return 0
    if sa1 <= slot < sa2:
        return 1
    return None


def _sum_hourly_for_day(
    slot_starts: Sequence[datetime],
    hourly_matched: Sequence[float],
    hourly_optimized: Sequence[float],
    *,
    sa0: datetime,
    sa1: datetime,
    sa2: datetime,
    day_index: int,
    index_end: int | None = None,
) -> tuple[float, float]:
    matched_total = 0.0
    optimized_total = 0.0
    limit = min(len(slot_starts), len(hourly_matched), len(hourly_optimized))
    if index_end is not None:
        limit = min(limit, index_end)
    for index in range(limit):
        if _slot_day_index(slot_starts[index], sa0, sa1, sa2) != day_index:
            continue
        matched_total += float(hourly_matched[index] or 0.0)
        optimized_total += float(hourly_optimized[index] or 0.0)
    return matched_total, optimized_total


def _day_slot_counts(
    slot_starts: Sequence[datetime],
    *,
    sa0: datetime,
    sa1: datetime,
    sa2: datetime,
    day_index: int,
    history_slot_count: int,
) -> tuple[int, int]:
    """Return (slots_in_day, history_slots_in_day)."""
    total = 0
    history = 0
    for index, slot in enumerate(slot_starts):
        if _slot_day_index(slot, sa0, sa1, sa2) != day_index:
            continue
        total += 1
        if index < history_slot_count:
            history += 1
    return total, history


def _build_day_totals(
    *,
    label: str,
    matched: float,
    optimized: float,
    achieved_matched: float | None,
    achieved_optimized: float | None,
    day_slots: int,
    history_in_day: int,
) -> DayCostTotals:
    running = day_slots > 0 and 0 < history_in_day < day_slots
    return DayCostTotals(
        label=label,
        matched_baseline_cost_euro=matched,
        optimized_cost_euro=optimized,
        achieved_matched_cost_euro=achieved_matched if running else None,
        achieved_optimized_cost_euro=achieved_optimized if running else None,
        show_split_savings=running,
    )


def _segment_day_totals(
    chart: UiChartWindow,
    hourly_matched: Sequence[float],
    hourly_optimized: Sequence[float],
    hist: int,
) -> DayCostTotals:
    """Totals for a single SA segment (whole series belongs to one day)."""
    tag = "SA₀→SA₁" if chart.segment_index == 0 else "SA₁→SA₂"
    day_start = chart.sa0 if chart.segment_index == 0 else chart.sa1
    limit = min(
        len(chart.slot_datetimes), len(hourly_matched), len(hourly_optimized)
    )
    hist_end = min(hist, limit)
    return _build_day_totals(
        label=_day_label(day_start, tag),
        matched=sum(float(hourly_matched[i] or 0.0) for i in range(limit)),
        optimized=sum(float(hourly_optimized[i] or 0.0) for i in range(limit)),
        achieved_matched=sum(
            float(hourly_matched[i] or 0.0) for i in range(hist_end)
        ),
        achieved_optimized=sum(
            float(hourly_optimized[i] or 0.0) for i in range(hist_end)
        ),
        day_slots=limit,
        history_in_day=hist_end,
    )


def _full_span_day_totals(
    chart: UiChartWindow,
    hourly_matched: Sequence[float],
    hourly_optimized: Sequence[float],
    hist: int,
    day: tuple[int, str, datetime],
) -> DayCostTotals:
    """Totals for one SA-day of a full SA₀→SA₂ span."""
    day_index, tag, day_start = day
    slots = chart.slot_datetimes
    bounds = dict(sa0=chart.sa0, sa1=chart.sa1, sa2=chart.sa2)
    matched, optimized = _sum_hourly_for_day(
        slots,
        hourly_matched,
        hourly_optimized,
        day_index=day_index,
        **bounds,
    )
    achieved_matched, achieved_optimized = _sum_hourly_for_day(
        slots,
        hourly_matched,
        hourly_optimized,
        day_index=day_index,
        index_end=hist,
        **bounds,
    )
    day_slots, history_in_day = _day_slot_counts(
        slots,
        day_index=day_index,
        history_slot_count=hist,
        **bounds,
    )
    return _build_day_totals(
        label=_day_label(day_start, tag),
        matched=matched,
        optimized=optimized,
        achieved_matched=achieved_matched,
        achieved_optimized=achieved_optimized,
        day_slots=day_slots,
        history_in_day=history_in_day,
    )


def day_cost_totals_for_chart(
    chart: UiChartWindow,
    hourly_matched: Sequence[float],
    hourly_optimized: Sequence[float],
    *,
    history_slot_count: int = 0,
) -> tuple[DayCostTotals, ...]:
    """Sum aligned hourly costs per SA-day; one day on segment, two on full span.

    On a partially elapsed (running) day, sets ``show_split_savings`` with achieved
    totals for history slots so annotations can show bisher vs erwartet.
    """
    if not chart.slot_datetimes or not hourly_matched or not hourly_optimized:
        return ()
    hist = max(0, int(history_slot_count))
    if chart.span != "full":
        return (_segment_day_totals(chart, hourly_matched, hourly_optimized, hist),)
    return tuple(
        _full_span_day_totals(chart, hourly_matched, hourly_optimized, hist, day)
        for day in ((0, "SA₀→SA₁", chart.sa0), (1, "SA₁→SA₂", chart.sa1))
    )


def achieved_savings_cumulative_euro(
    slot_starts: Sequence[datetime],
    hourly_savings: Sequence[float],
    *,
    history_slot_count: int,
    sa0: datetime,
    sa1: datetime,
    sa2: datetime,
) -> list[float]:
    """Plan-based cumsum of hourly_savings in gray/history only; reset at SA₁.

    Values outside the history region are NaN so the trace stops at the gray boundary.
    Positive increment = Optimiert günstiger als BL Ziel (same as hourly_savings_euro).
    """
    length = len(slot_starts)
    series = [float("nan")] * length
    if history_slot_count <= 0 or length == 0 or not hourly_savings:
        return series

    day_running = [0.0, 0.0]
    hist_end = min(history_slot_count, length, len(hourly_savings))
    for index in range(hist_end):
        day_index = _slot_day_index(slot_starts[index], sa0, sa1, sa2)
        if day_index is None:
            continue
        day_running[day_index] += float(hourly_savings[index] or 0.0)
        series[index] = day_running[day_index]
    return series
