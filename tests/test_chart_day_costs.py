"""Unit tests for Chart 2 SA-day cost KPIs and achieved-savings series."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from data.planning_window import compute_ui_s2_chart_window, compute_sunrise_anchors
from ui.chart_day_costs import (
    achieved_savings_cumulative_euro,
    day_cost_totals_for_chart,
)
from ui.chart_decorations import _cost_summary_annotations

LAT = 47.404
LON = 9.743
TZ = "Europe/Vienna"
_TZ = ZoneInfo(TZ)


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_TZ)


def test_day_cost_totals_segment_sums_visible_day_only():
    now = _dt(2026, 6, 15, 14, 0)
    anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
    chart = compute_ui_s2_chart_window(anchors, segment_index=0, span="segment")
    n = len(chart.slot_datetimes)
    matched = [1.0] * n
    optimized = [0.4] * n
    days = day_cost_totals_for_chart(chart, matched, optimized)
    assert len(days) == 1
    assert days[0].matched_baseline_cost_euro == pytest.approx(float(n))
    assert days[0].optimized_cost_euro == pytest.approx(0.4 * n)
    assert "SA₀→SA₁" in days[0].label
    assert days[0].show_split_savings is False


def test_day_cost_totals_running_day_splits_achieved_and_expected():
    now = _dt(2026, 6, 15, 14, 0)
    anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
    chart = compute_ui_s2_chart_window(anchors, segment_index=0, span="segment")
    n = len(chart.slot_datetimes)
    history = n // 3
    matched = [1.0] * n
    optimized = [0.4] * n
    days = day_cost_totals_for_chart(
        chart, matched, optimized, history_slot_count=history
    )
    assert len(days) == 1
    day = days[0]
    assert day.show_split_savings is True
    assert day.achieved_matched_cost_euro == pytest.approx(float(history))
    assert day.achieved_optimized_cost_euro == pytest.approx(0.4 * history)
    assert day.achieved_savings_euro == pytest.approx(0.4 * history - float(history))
    assert day.savings_euro == pytest.approx(0.4 * n - float(n))
    annotations = _cost_summary_annotations(days=days)
    texts = [ann["text"] for ann in annotations]
    assert any(t.startswith("Ersparnis bisher:") for t in texts)
    assert any(t.startswith("Ersparnis erwartet:") for t in texts)
    assert not any(t.startswith("Ersparnis:") and "bisher" not in t and "erwartet" not in t for t in texts)


def test_day_cost_totals_full_span_two_columns():
    now = _dt(2026, 6, 15, 14, 0)
    anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
    chart = compute_ui_s2_chart_window(anchors, segment_index=0, span="full")
    matched = []
    optimized = []
    for slot in chart.slot_datetimes:
        if slot < chart.sa1:
            matched.append(1.0)
            optimized.append(0.5)
        else:
            matched.append(2.0)
            optimized.append(1.0)
    day0_slots = sum(1 for slot in chart.slot_datetimes if chart.sa0 <= slot < chart.sa1)
    history = day0_slots // 2
    days = day_cost_totals_for_chart(
        chart, matched, optimized, history_slot_count=history
    )
    assert len(days) == 2
    day1_slots = sum(1 for slot in chart.slot_datetimes if chart.sa1 <= slot < chart.sa2)
    assert days[0].matched_baseline_cost_euro == pytest.approx(float(day0_slots))
    assert days[1].matched_baseline_cost_euro == pytest.approx(2.0 * day1_slots)
    assert days[0].show_split_savings is True
    assert days[1].show_split_savings is False
    annotations = _cost_summary_annotations(days=days)
    xs = {ann["x"] for ann in annotations}
    assert xs == {0.01, 0.52}
    assert any("SA₀→SA₁" in ann["text"] for ann in annotations)
    assert any("SA₁→SA₂" in ann["text"] for ann in annotations)
    assert any("Ersparnis bisher:" in ann["text"] for ann in annotations)
    assert any("Ersparnis erwartet:" in ann["text"] for ann in annotations)


def test_achieved_savings_cumsum_history_only_resets_at_sa1():
    sa0 = _dt(2026, 6, 15, 5, 0)
    sa1 = sa0 + timedelta(hours=24)
    sa2 = sa1 + timedelta(hours=24)
    slots = [sa0 + timedelta(hours=h) for h in range(30)]
    hourly = [0.1] * len(slots)
    history_slot_count = 28
    series = achieved_savings_cumulative_euro(
        slots,
        hourly,
        history_slot_count=history_slot_count,
        sa0=sa0,
        sa1=sa1,
        sa2=sa2,
    )
    assert series[0] == pytest.approx(0.1)
    assert series[23] == pytest.approx(2.4)
    assert series[24] == pytest.approx(0.1)
    assert series[27] == pytest.approx(0.4)
    assert math.isnan(series[28])
    assert math.isnan(series[29])
