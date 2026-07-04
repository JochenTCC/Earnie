"""Tests für Sunset-Planungshorizont und UI sunrise→sunrise."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from data.planning_window import (
    compute_planning_window,
    compute_ui_chart_window,
    compute_ui_chart_window_with_offset,
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
    def test_morning_run_includes_two_sunsets(self):
        now = _dt(2026, 6, 15, 10, 0)
        window = compute_planning_window(now, LAT, LON, TZ)
        assert window.sunset_1 > now
        assert window.sunset_2 > window.sunset_1
        assert window.end == window.sunset_2
        assert window.start == normalize_hour_slot(now)
        assert window.horizon_hours >= 24
        assert window.sunrise_anchor > now
        assert window.sunrise_anchor < window.sunset_2

    def test_late_evening_horizon_extends_past_tomorrow(self):
        now = _dt(2026, 6, 15, 22, 0)
        window = compute_planning_window(now, LAT, LON, TZ)
        assert window.sunset_1.date() == now.date() + timedelta(days=1)
        assert window.horizon_hours >= 40

    def test_afternoon_minimum_horizon_about_one_day(self):
        now = _dt(2026, 6, 15, 20, 30)
        window = compute_planning_window(now, LAT, LON, TZ)
        assert window.horizon_hours >= 23
        segment_a_hours = (window.sunset_1 - now).total_seconds() / 3600.0
        assert segment_a_hours < 1.5

    def test_sunrise_anchor_index_in_slots(self):
        now = _dt(2026, 6, 15, 14, 0)
        window = compute_planning_window(now, LAT, LON, TZ)
        idx = sunrise_anchor_slot_index(window)
        assert window.slot_datetimes[idx] == normalize_hour_slot(window.sunrise_anchor)


class TestUiChartWindow:
    def test_sunrise_to_sunrise_span(self):
        now = _dt(2026, 6, 15, 14, 0)
        chart = compute_ui_chart_window(now, LAT, LON, TZ)
        assert chart.start == previous_sunrise_before(now, LAT, LON, TZ)
        assert chart.end == next_sunrise_after(now, LAT, LON, TZ)
        assert chart.start < now < chart.end
        span_h = (chart.end - chart.start).total_seconds() / 3600.0
        assert 20 <= span_h <= 26

    def test_ui_zones_colors(self):
        now = _dt(2026, 6, 15, 14, 0)
        chart = compute_ui_chart_window(now, LAT, LON, TZ)
        zones = ui_chart_zones(now, chart)
        assert zones.history.fill_color is not None
        assert zones.live_plan.fill_color is None
        assert zones.forecast.fill_color is not None
        assert zones.history.start == chart.start
        assert zones.history.end == now
        assert zones.live_plan.start == now
        assert zones.live_plan.end == chart.next_sunrise
        assert zones.forecast.start == chart.next_sunrise
        assert zones.forecast.end == chart.end

    def test_ui_chart_offset_shifts_window_back(self):
        now = _dt(2026, 6, 15, 14, 0)
        current = compute_ui_chart_window(now, LAT, LON, TZ)
        previous = compute_ui_chart_window_with_offset(now, 1, LAT, LON, TZ)
        assert previous.start < current.start
        assert normalize_hour_slot(previous.end) <= normalize_hour_slot(current.start)


class TestValidation:
    def test_naive_datetime_rejected(self):
        naive = datetime(2026, 6, 15, 10, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            compute_planning_window(naive, LAT, LON, TZ)

    def test_empty_timezone_rejected(self):
        now = _dt(2026, 6, 15, 10, 0)
        with pytest.raises(ValueError, match="timezone_name"):
            compute_planning_window(now, LAT, LON, "")
