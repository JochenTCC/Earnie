"""Tests für optimizer.appliance_schedule."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from optimizer.appliance_schedule import apply_appliance_schedules_to_matrix

TZ = ZoneInfo("Europe/Vienna")


def _row(slot: datetime, baseload: float = 1.0) -> dict:
    return {
        "slot_datetime": slot,
        "expected_p_act": baseload,
        "expected_flex_kw": {},
        "expected_p_total": baseload,
    }


def test_apply_appliance_schedule_adds_baseload():
    start = datetime(2026, 7, 8, 18, 0, tzinfo=TZ)
    matrix = [
        _row(start),
        _row(datetime(2026, 7, 8, 19, 0, tzinfo=TZ)),
        _row(datetime(2026, 7, 8, 20, 0, tzinfo=TZ)),
    ]
    schedules = {
        "waschmaschine": {
            "start_at": start.isoformat(timespec="seconds"),
            "power_kw": 2.0,
            "runtime_h": 2.0,
            "expires_at": datetime(2026, 7, 8, 20, 0, tzinfo=TZ).isoformat(timespec="seconds"),
        }
    }
    updated = apply_appliance_schedules_to_matrix(matrix, schedules)
    assert updated[0]["expected_p_act"] == 3.0
    assert updated[1]["expected_p_act"] == 3.0
    assert updated[2]["expected_p_act"] == 1.0


def test_apply_appliance_schedule_empty_is_noop():
    matrix = [_row(datetime(2026, 7, 8, 18, 0, tzinfo=TZ))]
    assert apply_appliance_schedules_to_matrix(matrix, None) == matrix
