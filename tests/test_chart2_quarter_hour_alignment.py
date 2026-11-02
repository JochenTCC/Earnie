"""Ledger P1: Chart 2 maps quarter-hour plan values per exact slot (Σ chart = Σ snapshot)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from data.planning_window import compute_ui_chart_window
from runtime_store.history_chart_rows import _coerce_slot_start
from runtime_store.history_timeline import _slot_plan_increments_from_snapshots
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


def _log_entry(version: str, **lists: list[float]) -> dict:
    return {"written_by_app_version": version, "savings_snapshot": dict(lists)}


def test_history_quarter_snapshots_take_slot_zero_of_each_cycle():
    slots = [_dt(10, 0) + QUARTER * index for index in range(8)]
    cycle_values = [0.11, 0.12, 0.13, 0.14, -0.2, 0.0, 0.3, 0.05]
    by_slot = {
        _coerce_slot_start(slot): _log_entry(
            "2.7.0-beta.3", hourly_savings_euro=[value, 9.0, 9.0]
        )
        for slot, value in zip(slots, cycle_values)
    }

    planned = _slot_plan_increments_from_snapshots(by_slot, slots, "hourly_savings_euro")

    assert planned == pytest.approx(cycle_values)
    assert sum(planned) == pytest.approx(sum(cycle_values))


def test_history_quarter_snapshot_missing_cycle_leaves_slot_empty():
    slots = [_dt(10, 0) + QUARTER * index for index in range(4)]
    by_slot = {
        _coerce_slot_start(slots[0]): _log_entry("2.7.0", hourly_savings_euro=[0.4]),
        _coerce_slot_start(slots[2]): _log_entry("2.7.0", hourly_savings_euro=[0.2]),
    }

    planned = _slot_plan_increments_from_snapshots(by_slot, slots, "hourly_savings_euro")

    assert planned == pytest.approx([0.4, 0.0, 0.2, 0.0])


def test_history_hourly_snapshots_before_2_5_spread_over_the_hour():
    slots = [_dt(10, 0) + QUARTER * index for index in range(4)]
    by_slot = {
        _coerce_slot_start(slots[1]): _log_entry("2.4.0", hourly_savings_euro=[0.8]),
        _coerce_slot_start(slots[3]): _log_entry("2.4.0", hourly_savings_euro=[1.2]),
    }

    planned = _slot_plan_increments_from_snapshots(by_slot, slots, "hourly_savings_euro")

    # last entry of the hour carries the hour's value
    assert planned == pytest.approx([0.3, 0.3, 0.3, 0.3])


def test_history_unreadable_version_fails_loud():
    slot = _dt(10, 0)
    by_slot = {_coerce_slot_start(slot): _log_entry("x.y", hourly_savings_euro=[0.1])}

    with pytest.raises(ValueError, match="written_by_app_version"):
        _slot_plan_increments_from_snapshots(by_slot, [slot], "hourly_savings_euro")
