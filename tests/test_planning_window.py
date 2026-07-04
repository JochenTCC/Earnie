"""Tests für Sunset-Planungshorizont und UI Sunset-2-Sunset."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from data.planning_window import (
    compute_planning_window,
    compute_sunrise_anchors,
    compute_ui_chart_window,
    compute_ui_chart_window_with_offset,
    is_sunrise_hour,
    normalize_hour_slot,
    official_sun_times,
    previous_sunrise_before,
    next_sunrise_after,
    sunrise_anchor_slot_index,
    ui_chart_zones,
)

LAT = 47.404
LON = 9.743
TZ = "Europe/Vienna"


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(TZ))


class TestSunEvents:
    def test_june_sun_times_plausible(self):
        sunrise, sunset = official_sun_times(_dt(2026, 6, 15, 12).date(), LAT, LON, TZ)
        assert 4 <= sunrise.hour <= 6
        assert 20 <= sunset.hour <= 22


class TestPlanningWindow:
    def test_morning_run_extends_to_ui_sa2(self):
        now = _dt(2026, 6, 15, 10, 0)
        window = compute_planning_window(now, LAT, LON, TZ)
        anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
        assert window.sunset_1 > now
        assert window.sunset_2 > window.sunset_1
        assert normalize_hour_slot(window.end) == normalize_hour_slot(anchors.sa2)
        assert window.end > window.sunset_2
        assert window.start == normalize_hour_slot(now)
        assert window.horizon_hours >= 28
        assert window.sunrise_anchor > now
        assert window.sunrise_anchor < window.end

    def test_late_evening_horizon_extends_past_second_sunrise(self):
        now = _dt(2026, 6, 15, 22, 0)
        window = compute_planning_window(now, LAT, LON, TZ)
        assert window.sunset_1.date() == now.date() + timedelta(days=1)
        assert window.horizon_hours >= 30

    def test_afternoon_horizon_covers_sa1_sa2_chart_segment(self):
        now = _dt(2026, 6, 15, 14, 0)
        window = compute_planning_window(now, LAT, LON, TZ)
        chart1 = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=1)
        assert window.horizon_hours >= 23
        assert normalize_hour_slot(window.end) == normalize_hour_slot(chart1.end)

    def test_evening_run_first_sunset_soon(self):
        now = _dt(2026, 6, 15, 20, 30)
        window = compute_planning_window(now, LAT, LON, TZ)
        segment_a_hours = (window.sunset_1 - now).total_seconds() / 3600.0
        assert segment_a_hours < 1.5

    def test_sunrise_anchor_index_in_slots(self):
        now = _dt(2026, 6, 15, 14, 0)
        window = compute_planning_window(now, LAT, LON, TZ)
        idx = sunrise_anchor_slot_index(window)
        assert window.slot_datetimes[idx] == normalize_hour_slot(window.sunrise_anchor)


class TestSunriseAnchors:
    def test_afternoon_anchors_use_last_and_next_sunrise(self):
        now = _dt(2026, 6, 15, 14, 0)
        anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
        assert anchors.sa0 == previous_sunrise_before(now, LAT, LON, TZ)
        assert anchors.sa1 == next_sunrise_after(now, LAT, LON, TZ)
        assert anchors.sa2 == next_sunrise_after(anchors.sa1, LAT, LON, TZ)

    def test_sunrise_hour_anchors_use_now_and_tomorrow(self):
        sunrise, _ = official_sun_times(_dt(2026, 6, 15, 12).date(), LAT, LON, TZ)
        now = sunrise + timedelta(minutes=20)
        assert is_sunrise_hour(now, LAT, LON, TZ)
        anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
        assert anchors.sa0 == now
        assert anchors.sa1.date() == now.date() + timedelta(days=1)
        assert anchors.sa2.date() == now.date() + timedelta(days=2)


class TestUiChartWindow:
    def test_segment_zero_spans_sa0_to_sa1(self):
        now = _dt(2026, 6, 15, 14, 0)
        anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
        chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=0)
        assert chart.start == anchors.sa0
        assert chart.end == anchors.sa1
        assert chart.segment_index == 0
        span_h = (chart.end - chart.start).total_seconds() / 3600.0
        assert 20 <= span_h <= 26

    def test_segment_one_spans_sa1_to_sa2(self):
        now = _dt(2026, 6, 15, 14, 0)
        anchors = compute_sunrise_anchors(now, LAT, LON, TZ)
        chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=1)
        assert chart.start == anchors.sa1
        assert chart.end == anchors.sa2
        assert chart.segment_index == 1

    def test_ui_zones_segment_one_no_gray_green_on_extrapolated(self):
        now = _dt(2026, 6, 15, 14, 0)
        chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=1)
        rows = [
            {
                "slot_datetime": slot,
                "Preis extrapoliert": slot >= _dt(2026, 6, 16, 10, 0),
            }
            for slot in chart.slot_datetimes
        ]
        zones = ui_chart_zones(now, chart, sim_rows=rows)
        assert zones.history.fill_color is None
        assert zones.history.end == zones.history.start
        assert zones.forecast.fill_color is not None
        assert zones.forecast.start == _dt(2026, 6, 16, 10, 0)
        assert zones.live_plan.end == zones.forecast.start

    def test_ui_zones_gray_neutral_green(self):
        now = _dt(2026, 6, 15, 14, 0)
        chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=0)
        rows = [
            {
                "slot_datetime": _dt(2026, 6, 15, hour, 0),
                "Preis extrapoliert": hour >= 18,
            }
            for hour in range(5, 20)
        ]
        zones = ui_chart_zones(now, chart, sim_rows=rows)
        assert zones.history.fill_color is not None
        assert zones.live_plan.fill_color is None
        assert zones.forecast.fill_color is not None
        assert zones.history.end == normalize_hour_slot(now)
        assert zones.forecast.start == _dt(2026, 6, 15, 18, 0)

    def test_ui_chart_offset_shifts_anchors_back(self):
        now = _dt(2026, 6, 15, 14, 0)
        current = compute_ui_chart_window(now, LAT, LON, TZ)
        previous = compute_ui_chart_window_with_offset(now, 1, LAT, LON, TZ)
        assert previous.sa0 < current.sa0
        assert normalize_hour_slot(previous.sa1) == normalize_hour_slot(current.sa0)


class TestValidation:
    def test_naive_datetime_rejected(self):
        naive = datetime(2026, 6, 15, 10, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            compute_planning_window(naive, LAT, LON, TZ)

    def test_empty_timezone_rejected(self):
        now = _dt(2026, 6, 15, 10, 0)
        with pytest.raises(ValueError, match="timezone_name"):
            compute_planning_window(now, LAT, LON, "")
