"""Unit tests for Chart 2 SA-day cost KPIs."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from data.planning_window import compute_ui_s2_chart_window, compute_sunrise_anchors
from ui.chart_day_costs import day_cost_totals_for_chart
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


def _ledger(day_start: datetime, *, saving: float = 0.5, correction: float = -0.1) -> dict:
    return {
        "cumulative_euro": [],
        "open_day_start": day_start.isoformat(),
        "open_day_end": (day_start + timedelta(hours=24)).isoformat(),
        "saving_euro": saving,
        "soc_correction_euro": correction,
        "closed_days": [],
        "hint": None,
    }


def test_day_cost_totals_running_day_takes_bisher_from_the_ledger():
    now = _dt(2026, 6, 15, 14, 0)
    anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
    chart = compute_ui_s2_chart_window(anchors, segment_index=0, span="segment")
    n = len(chart.slot_datetimes)
    history = n // 3
    matched = [1.0] * n
    optimized = [0.4] * n
    days = day_cost_totals_for_chart(
        chart, matched, optimized, history_slot_count=history, ledger=_ledger(chart.sa0)
    )
    assert len(days) == 1
    day = days[0]
    assert day.show_split_savings is True
    assert day.achieved_saving_euro == pytest.approx(0.5)
    assert day.achieved_soc_correction_euro == pytest.approx(-0.1)
    assert day.savings_euro == pytest.approx(float(n) - 0.4 * n)
    annotations = _cost_summary_annotations(days=days)
    texts = [ann["text"] for ann in annotations]
    assert "Bisher: 0.50 € gespart" in texts
    assert "SoC: 0.10 € abgezogen" in texts
    assert any(t.startswith("Erwartet: ") and t.endswith(" € gespart") for t in texts)
    assert not any(t.startswith("Ergebnis:") for t in texts)


def test_day_that_has_not_started_is_labelled_plan():
    now = _dt(2026, 6, 15, 14, 0)
    anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
    chart = compute_ui_s2_chart_window(anchors, segment_index=0, span="segment")
    n = len(chart.slot_datetimes)
    days = day_cost_totals_for_chart(
        chart, [1.0] * n, [0.4] * n, history_slot_count=0, ledger=_ledger(chart.sa0 + timedelta(days=3))
    )

    texts = [ann["text"] for ann in _cost_summary_annotations(days=days)]

    assert any(t.startswith("Plan: ") and t.endswith(" € gespart") for t in texts)
    assert not any(t.startswith(("Ergebnis:", "Bisher:", "Erwartet:")) for t in texts)


def test_day_cost_totals_running_day_without_ledger_shows_only_erwartet():
    now = _dt(2026, 6, 15, 14, 0)
    anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
    chart = compute_ui_s2_chart_window(anchors, segment_index=0, span="segment")
    n = len(chart.slot_datetimes)
    days = day_cost_totals_for_chart(
        chart, [1.0] * n, [0.4] * n, history_slot_count=n // 3
    )
    texts = [ann["text"] for ann in _cost_summary_annotations(days=days)]
    assert any(t.startswith("Erwartet:") for t in texts)
    assert not any(t.startswith("Bisher:") for t in texts)


def test_day_cost_totals_elapsed_day_shows_only_the_ledger_result():
    now = _dt(2026, 6, 15, 14, 0)
    anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
    chart = compute_ui_s2_chart_window(anchors, segment_index=0, span="segment")
    n = len(chart.slot_datetimes)
    ledger = {
        **_ledger(chart.sa0 + timedelta(days=3)),
        "closed_days": [
            {
                "day_start": chart.sa0.isoformat(),
                "day_end": (chart.sa0 + timedelta(hours=24)).isoformat(),
                "saving_adjusted_eur": 0.42,
                "incomplete": True,
            }
        ],
    }
    days = day_cost_totals_for_chart(
        chart, [0.0] * n, [0.0] * n, history_slot_count=n, ledger=ledger
    )
    assert days[0].history_only is True
    texts = [ann["text"] for ann in _cost_summary_annotations(days=days)]
    assert texts == ["Ergebnis: 0.42 € gespart", "unvollständig"]


def test_full_span_marks_only_the_incomplete_elapsed_day():
    """Desktop span SA₀→SA₂: the marker belongs to the incomplete day alone."""
    now = _dt(2026, 6, 15, 14, 0)
    anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
    chart = compute_ui_s2_chart_window(anchors, segment_index=0, span="full")
    n = len(chart.slot_datetimes)
    closed = [
        {
            "day_start": chart.sa0.isoformat(),
            "day_end": chart.sa1.isoformat(),
            "saving_adjusted_eur": -0.42,
            "incomplete": True,
        },
        {
            "day_start": chart.sa1.isoformat(),
            "day_end": chart.sa2.isoformat(),
            "saving_adjusted_eur": 0.3,
            "incomplete": False,
        },
    ]
    ledger = {**_ledger(chart.sa2 + timedelta(days=3)), "closed_days": closed}

    days = day_cost_totals_for_chart(
        chart, [0.0] * n, [0.0] * n, history_slot_count=n, ledger=ledger
    )

    texts = [ann["text"] for ann in _cost_summary_annotations(days=days)]
    assert "Ergebnis: 0.42 € mehr ausgegeben" in texts
    assert "Ergebnis: 0.30 € gespart" in texts
    assert texts.count("unvollständig") == 1


def test_day_cost_totals_elapsed_day_without_ledger_invents_no_figure():
    now = _dt(2026, 6, 15, 14, 0)
    anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
    chart = compute_ui_s2_chart_window(anchors, segment_index=0, span="segment")
    n = len(chart.slot_datetimes)
    days = day_cost_totals_for_chart(chart, [0.0] * n, [0.0] * n, history_slot_count=n)
    assert _cost_summary_annotations(days=days) == []


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
        chart, matched, optimized, history_slot_count=history, ledger=_ledger(chart.sa0)
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
    assert any(ann["text"].startswith("Bisher:") for ann in annotations)
    assert any(ann["text"].startswith("Erwartet:") for ann in annotations)
