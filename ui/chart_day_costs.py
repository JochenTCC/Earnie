"""SA-day cost KPI totals for Chart 2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from data.planning_window import UiChartWindow
from ui.chart_ledger_savings import ledger_figures_for_day


@dataclass(frozen=True)
class DayCostTotals:
    """BL/Optimiert/Ersparnis for one sunrise→sunrise day in the visible window.

    ``savings_euro`` is positive when the plan is cheaper than BL Ziel. On a running
    day (``show_split_savings``) the plan values cover the rest of the day, and the
    realised part comes from the savings ledger. A fully elapsed day
    (``history_only``) has no plan values, only its ledger figure.
    """

    label: str
    matched_baseline_cost_euro: float
    optimized_cost_euro: float
    show_split_savings: bool = False
    history_only: bool = False
    achieved_saving_euro: float | None = None
    achieved_soc_correction_euro: float | None = None
    closed_saving_euro: float | None = None
    closed_incomplete: bool = False

    @property
    def savings_euro(self) -> float:
        return self.matched_baseline_cost_euro - self.optimized_cost_euro


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
    day_start: datetime,
    day_slots: int,
    history_in_day: int,
    ledger: dict | None,
) -> DayCostTotals:
    running = day_slots > 0 and 0 < history_in_day < day_slots
    history_only = day_slots > 0 and history_in_day == day_slots
    figures = ledger_figures_for_day(ledger, day_start)
    closed_saving = figures["closed_saving_euro"]
    if history_only and figures["saving_euro"] is not None:
        closed_saving = figures["saving_euro"] + figures["soc_correction_euro"]
    return DayCostTotals(
        label=label,
        matched_baseline_cost_euro=matched,
        optimized_cost_euro=optimized,
        show_split_savings=running,
        history_only=history_only,
        achieved_saving_euro=figures["saving_euro"] if running else None,
        achieved_soc_correction_euro=figures["soc_correction_euro"] if running else None,
        closed_saving_euro=closed_saving if history_only else None,
        closed_incomplete=bool(figures["incomplete"]) if history_only else False,
    )


def _segment_day_totals(
    chart: UiChartWindow,
    hourly_matched: Sequence[float],
    hourly_optimized: Sequence[float],
    hist: int,
    ledger: dict | None,
) -> DayCostTotals:
    """Totals for a single SA segment (whole series belongs to one day)."""
    tag = "SA₀→SA₁" if chart.segment_index == 0 else "SA₁→SA₂"
    day_start = chart.sa0 if chart.segment_index == 0 else chart.sa1
    limit = min(
        len(chart.slot_datetimes), len(hourly_matched), len(hourly_optimized)
    )
    return _build_day_totals(
        label=_day_label(day_start, tag),
        matched=sum(float(hourly_matched[i] or 0.0) for i in range(limit)),
        optimized=sum(float(hourly_optimized[i] or 0.0) for i in range(limit)),
        day_start=day_start,
        day_slots=limit,
        history_in_day=min(hist, limit),
        ledger=ledger,
    )


def _full_span_day_totals(
    chart: UiChartWindow,
    hourly_matched: Sequence[float],
    hourly_optimized: Sequence[float],
    hist: int,
    day: tuple[int, str, datetime],
    ledger: dict | None,
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
        day_start=day_start,
        day_slots=day_slots,
        history_in_day=history_in_day,
        ledger=ledger,
    )


def day_cost_totals_for_chart(
    chart: UiChartWindow,
    hourly_matched: Sequence[float],
    hourly_optimized: Sequence[float],
    *,
    history_slot_count: int = 0,
    ledger: dict | None = None,
) -> tuple[DayCostTotals, ...]:
    """Sum aligned plan costs per SA-day; one day on segment, two on full span.

    ``ledger`` is ``savings_view["ledger_savings"]``; it supplies the realised savings
    of a running or fully elapsed day.
    """
    if not chart.slot_datetimes or not hourly_matched or not hourly_optimized:
        return ()
    hist = max(0, int(history_slot_count))
    if chart.span != "full":
        return (_segment_day_totals(chart, hourly_matched, hourly_optimized, hist, ledger),)
    return tuple(
        _full_span_day_totals(chart, hourly_matched, hourly_optimized, hist, day, ledger)
        for day in ((0, "SA₀→SA₁", chart.sa0), (1, "SA₁→SA₂", chart.sa1))
    )
