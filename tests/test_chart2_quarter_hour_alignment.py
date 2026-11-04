"""Ledger P1: Chart 2 maps quarter-hour plan values per exact slot."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from data.planning_window import compute_ui_chart_window
from ui.chart_context import align_hourly_increments_to_display_slots

TZ = "Europe/Vienna"
LAT, LON = 47.404, 9.743
QUARTER = timedelta(minutes=15)


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 15, hour, minute, tzinfo=ZoneInfo(TZ))


def _chart():
    return compute_ui_chart_window(_dt(14, 30), LAT, LON, TZ, segment_index=0)


def _quarter_matrix(start: datetime, count: int) -> list[dict]:
    return [{"slot_datetime": start + QUARTER * index} for index in range(count)]


def test_quarter_matrix_on_quarter_slots_maps_each_row_to_its_slot():
    matrix = _quarter_matrix(_dt(14, 0), 8)
    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    slots = tuple(row["slot_datetime"] for row in matrix)

    increments = align_hourly_increments_to_display_slots(values, matrix, _chart(), slots)

    assert increments == pytest.approx(values)


def test_quarter_matrix_on_mixed_axis_sums_four_rows_into_hourly_slot():
    """Display: quarter-hours of the running hour, then hourly slots (mixed axis)."""
    matrix = _quarter_matrix(_dt(14, 0), 12)
    values = [float(index + 1) for index in range(12)]
    slots = (_dt(14, 0), _dt(14, 15), _dt(14, 30), _dt(14, 45), _dt(15, 0), _dt(16, 0))

    increments = align_hourly_increments_to_display_slots(values, matrix, _chart(), slots)

    assert increments[:4] == pytest.approx([1.0, 2.0, 3.0, 4.0])
    assert increments[4] == pytest.approx(5.0 + 6.0 + 7.0 + 8.0)
    assert increments[5] == pytest.approx(9.0 + 10.0 + 11.0 + 12.0)
    assert sum(increments) == pytest.approx(sum(values))


def test_quarter_matrix_does_not_spread_the_full_hour_row():
    """Regression D2: only the :00 row matched and was spread over four slots."""
    matrix = _quarter_matrix(_dt(14, 0), 4)
    values = [2.0, 0.0, 0.0, 0.0]
    slots = tuple(row["slot_datetime"] for row in matrix)

    increments = align_hourly_increments_to_display_slots(values, matrix, _chart(), slots)

    assert increments == pytest.approx([2.0, 0.0, 0.0, 0.0])
