"""Tests für S-2-Navigation (Zyklus + Segment)."""
from __future__ import annotations

from ui.s2_navigation import (
    apply_s2_nav_back,
    apply_s2_nav_forward,
    s2_back_disabled,
    s2_forward_disabled,
)


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
