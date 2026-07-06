"""Tests für S-2-Navigation (Zyklus + Segment, Spec §4)."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from data.planning_window import compute_ui_chart_window, normalize_hour_slot, normalize_planning_hour_slot
from ui.chart_context import (
    build_live_chart_context,
    cycle_offset_for_sa0_date,
    max_sunrise_cycle_offset,
    sa0_date_for_s2_cycle,
    s2_navigable_cycles,
    segment_navigation_label,
)
from ui.s2_navigation import (
    apply_s2_nav_back,
    apply_s2_nav_forward,
    apply_s2_nav_heute,
    s2_back_disabled,
    s2_forward_disabled,
    s2_heute_disabled,
)

LAT = 47.404
LON = 9.743
TZ = "Europe/Vienna"


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(TZ))


def test_forward_from_live_goes_to_forecast_segment():
    assert apply_s2_nav_forward(0, 0) == (0, 1)


def test_forward_from_past_cycle_decrements_offset():
    assert apply_s2_nav_forward(2, 0) == (1, 0)
    assert apply_s2_nav_forward(1, 0) == (0, 0)


def test_back_from_forecast_returns_to_live_segment():
    assert apply_s2_nav_back(0, 1, max_cycle=3) == (0, 0)


def test_back_from_live_segment_increments_cycle_and_resets_segment():
    assert apply_s2_nav_back(0, 0, max_cycle=3) == (1, 0)


def test_back_at_max_cycle_unchanged():
    assert apply_s2_nav_back(3, 0, max_cycle=3) == (3, 0)
    assert s2_back_disabled(3, 0, max_cycle=3) is True


def test_forward_disabled_on_forecast_segment():
    assert s2_forward_disabled(0, 1) is True
    assert apply_s2_nav_forward(0, 1) == (0, 1)


def test_heute_disabled_only_on_live_segment():
    assert s2_heute_disabled(0, 0) is True
    assert s2_heute_disabled(0, 1) is False
    assert s2_heute_disabled(2, 0) is False


def test_apply_s2_nav_heute_returns_live():
    assert apply_s2_nav_heute() == (0, 0)


def test_s2_navigable_cycles_without_log(monkeypatch):
    monkeypatch.setattr(
        "ui.chart_context.optimization_history.earliest_replay_completed_at",
        lambda: None,
    )
    now = _dt(2026, 6, 15, 14, 0)
    cycles = s2_navigable_cycles(now)
    assert len(cycles) == 1
    assert cycles[0][0] == 0


def test_cycle_offset_for_sa0_date_matches_navigable_cycles(monkeypatch):
    earliest = datetime(2026, 6, 10, 8, 0)
    monkeypatch.setattr(
        "ui.chart_context.optimization_history.earliest_replay_completed_at",
        lambda: earliest,
    )
    now = _dt(2026, 6, 15, 14, 0)
    for offset, sa0 in s2_navigable_cycles(now):
        assert cycle_offset_for_sa0_date(sa0.date(), now) == offset
    assert cycle_offset_for_sa0_date(date(1999, 1, 1), now) is None


def test_sa0_date_for_s2_cycle_matches_chart_window():
    now = _dt(2026, 6, 15, 14, 0)
    live = build_live_chart_context(0, 0, now=now)
    past = build_live_chart_context(1, 0, now=now)
    assert sa0_date_for_s2_cycle(0, now=now) == live.chart_window.sa0.date()
    assert sa0_date_for_s2_cycle(1, now=now) == past.chart_window.sa0.date()


def test_round_trip_back_then_forward_reaches_live():
    cycle, segment = 0, 0
    cycle, segment = apply_s2_nav_back(cycle, segment, max_cycle=5)
    assert (cycle, segment) == (1, 0)
    cycle, segment = apply_s2_nav_forward(cycle, segment)
    assert (cycle, segment) == (0, 0)


def test_live_forecast_back_forward_cycle():
    cycle, segment = 0, 0
    cycle, segment = apply_s2_nav_forward(cycle, segment)
    assert (cycle, segment) == (0, 1)
    cycle, segment = apply_s2_nav_back(cycle, segment, max_cycle=5)
    assert (cycle, segment) == (0, 0)


def test_segment_navigation_label_live_and_past_cycle():
    now = _dt(2026, 6, 15, 14, 0)
    live_chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=0, cycle_offset=0)
    past_chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=0, cycle_offset=1)
    forecast_chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=1, cycle_offset=0)

    assert segment_navigation_label(live_chart, cycle_offset=0, segment_index=0).startswith(
        "SA₀→SA₁ (Live) · "
    )
    assert segment_navigation_label(past_chart, cycle_offset=1, segment_index=0).startswith(
        "SA₀→SA₁ · "
    )
    assert "(Live)" not in segment_navigation_label(
        past_chart, cycle_offset=1, segment_index=0
    )
    assert segment_navigation_label(
        forecast_chart, cycle_offset=0, segment_index=1
    ).startswith("SA₁→SA₂ (Vorausschau) · ")


def test_max_sunrise_cycle_offset_without_log_is_zero(monkeypatch):
    monkeypatch.setattr(
        "ui.chart_context.optimization_history.earliest_replay_completed_at",
        lambda: None,
    )
    assert max_sunrise_cycle_offset(_dt(2026, 6, 15, 14, 0)) == 0


def test_max_sunrise_cycle_offset_stops_before_earliest_log(monkeypatch):
    earliest = datetime(2026, 6, 10, 8, 0)
    monkeypatch.setattr(
        "ui.chart_context.optimization_history.earliest_replay_completed_at",
        lambda: earliest,
    )
    now = _dt(2026, 6, 15, 14, 0)
    max_cycle = max_sunrise_cycle_offset(now)
    assert max_cycle >= 1
    earliest_slot = normalize_planning_hour_slot(earliest, TZ)
    at_max = compute_ui_chart_window(now, LAT, LON, TZ, cycle_offset=max_cycle)
    assert normalize_hour_slot(at_max.sa0) >= earliest_slot
    beyond = compute_ui_chart_window(now, LAT, LON, TZ, cycle_offset=max_cycle + 1)
    assert normalize_hour_slot(beyond.sa0) < earliest_slot


def test_build_live_chart_context_segment_windows():
    now = _dt(2026, 6, 15, 14, 0)
    live = build_live_chart_context(0, 0, now=now)
    forecast = build_live_chart_context(0, 1, now=now)

    assert live.chart_window.segment_index == 0
    assert live.chart_window.start == live.chart_window.sa0
    assert live.chart_window.end == live.chart_window.sa1

    assert forecast.chart_window.segment_index == 1
    assert forecast.chart_window.start == forecast.chart_window.sa1
    assert forecast.chart_window.end == forecast.chart_window.sa2


def test_build_live_chart_context_cycle_offset_shifts_anchors():
    now = _dt(2026, 6, 15, 14, 0)
    live = build_live_chart_context(0, 0, now=now)
    past = build_live_chart_context(1, 0, now=now)

    assert past.cycle_offset == 1
    assert past.chart_window.sa0 < live.chart_window.sa0
    assert normalize_hour_slot(past.chart_window.sa1) == normalize_hour_slot(
        live.chart_window.sa0
    )


def test_build_live_chart_context_zone_reference_by_segment():
    now = _dt(2026, 6, 15, 14, 0)
    live = build_live_chart_context(0, 0, now=now)
    forecast = build_live_chart_context(0, 1, now=now)
    past = build_live_chart_context(1, 0, now=now)

    assert live.zone_reference == now
    assert forecast.zone_reference == forecast.chart_window.end
    assert past.zone_reference == past.chart_window.end


def test_build_live_chart_context_rejects_invalid_state():
    now = _dt(2026, 6, 15, 14, 0)
    with pytest.raises(ValueError, match="cycle_offset"):
        build_live_chart_context(-1, 0, now=now)
    with pytest.raises(ValueError, match="segment_index"):
        build_live_chart_context(0, 2, now=now)


def test_navigation_respects_max_cycle_from_log(monkeypatch):
    earliest = datetime(2026, 6, 14, 8, 0)
    monkeypatch.setattr(
        "ui.chart_context.optimization_history.earliest_replay_completed_at",
        lambda: earliest,
    )
    now = _dt(2026, 6, 15, 14, 0)
    max_cycle = max_sunrise_cycle_offset(now)
    cycle, segment = apply_s2_nav_back(0, 0, max_cycle=max_cycle)
    assert cycle == min(1, max_cycle)
    assert segment == 0
    assert s2_back_disabled(max_cycle, 0, max_cycle=max_cycle) is True


def test_segment_navigation_label_live_and_past_cycle():
    now = _dt(2026, 6, 15, 14, 0)
    live_chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=0, cycle_offset=0)
    past_chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=0, cycle_offset=1)
    forecast_chart = compute_ui_chart_window(now, LAT, LON, TZ, segment_index=1, cycle_offset=0)

    assert segment_navigation_label(live_chart, cycle_offset=0, segment_index=0).startswith(
        "SA₀→SA₁ (Live) · "
    )
    assert segment_navigation_label(past_chart, cycle_offset=1, segment_index=0).startswith(
        "SA₀→SA₁ · "
    )
    assert "(Live)" not in segment_navigation_label(
        past_chart, cycle_offset=1, segment_index=0
    )
    assert segment_navigation_label(
        forecast_chart, cycle_offset=0, segment_index=1
    ).startswith("SA₁→SA₂ (Vorausschau) · ")


def test_max_sunrise_cycle_offset_without_log_is_zero(monkeypatch):
    monkeypatch.setattr(
        "ui.chart_context.optimization_history.earliest_replay_completed_at",
        lambda: None,
    )
    assert max_sunrise_cycle_offset(_dt(2026, 6, 15, 14, 0)) == 0


def test_max_sunrise_cycle_offset_stops_before_earliest_log(monkeypatch):
    earliest = datetime(2026, 6, 10, 8, 0)
    monkeypatch.setattr(
        "ui.chart_context.optimization_history.earliest_replay_completed_at",
        lambda: earliest,
    )
    now = _dt(2026, 6, 15, 14, 0)
    max_cycle = max_sunrise_cycle_offset(now)
    assert max_cycle >= 1
    earliest_slot = normalize_planning_hour_slot(earliest, TZ)
    at_max = compute_ui_chart_window(now, LAT, LON, TZ, cycle_offset=max_cycle)
    assert normalize_hour_slot(at_max.sa0) >= earliest_slot
    beyond = compute_ui_chart_window(now, LAT, LON, TZ, cycle_offset=max_cycle + 1)
    assert normalize_hour_slot(beyond.sa0) < earliest_slot


def test_build_live_chart_context_segment_windows():
    now = _dt(2026, 6, 15, 14, 0)
    live = build_live_chart_context(0, 0, now=now)
    forecast = build_live_chart_context(0, 1, now=now)

    assert live.chart_window.segment_index == 0
    assert live.chart_window.start == live.chart_window.sa0
    assert live.chart_window.end == live.chart_window.sa1

    assert forecast.chart_window.segment_index == 1
    assert forecast.chart_window.start == forecast.chart_window.sa1
    assert forecast.chart_window.end == forecast.chart_window.sa2


def test_build_live_chart_context_cycle_offset_shifts_anchors():
    now = _dt(2026, 6, 15, 14, 0)
    live = build_live_chart_context(0, 0, now=now)
    past = build_live_chart_context(1, 0, now=now)

    assert past.cycle_offset == 1
    assert past.chart_window.sa0 < live.chart_window.sa0
    assert normalize_hour_slot(past.chart_window.sa1) == normalize_hour_slot(
        live.chart_window.sa0
    )


def test_build_live_chart_context_zone_reference_by_segment():
    now = _dt(2026, 6, 15, 14, 0)
    live = build_live_chart_context(0, 0, now=now)
    forecast = build_live_chart_context(0, 1, now=now)
    past = build_live_chart_context(1, 0, now=now)

    assert live.zone_reference == now
    assert forecast.zone_reference == forecast.chart_window.end
    assert past.zone_reference == past.chart_window.end


def test_build_live_chart_context_rejects_invalid_state():
    now = _dt(2026, 6, 15, 14, 0)
    with pytest.raises(ValueError, match="cycle_offset"):
        build_live_chart_context(-1, 0, now=now)
    with pytest.raises(ValueError, match="segment_index"):
        build_live_chart_context(0, 2, now=now)


def test_navigation_respects_max_cycle_from_log(monkeypatch):
    earliest = datetime(2026, 6, 14, 8, 0)
    monkeypatch.setattr(
        "ui.chart_context.optimization_history.earliest_replay_completed_at",
        lambda: earliest,
    )
    now = _dt(2026, 6, 15, 14, 0)
    max_cycle = max_sunrise_cycle_offset(now)
    cycle, segment = apply_s2_nav_back(0, 0, max_cycle=max_cycle)
    assert cycle == min(1, max_cycle)
    assert segment == 0
    assert s2_back_disabled(max_cycle, 0, max_cycle=max_cycle) is True
