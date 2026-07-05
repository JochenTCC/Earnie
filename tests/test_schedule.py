"""Tests für Viertelstunden-Takt und main.py-Synchronisation."""
from __future__ import annotations

from datetime import datetime

from optimizer import schedule as s


def _slot_start(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 7, 5, hour, minute, second)


def test_ready_immediately_when_main_completed_in_current_slot():
    now = _slot_start(10, 0, 5)
    ready, reason, retry, fallback = s.live_simulation_readiness(
        "2026-07-05T10:00:01", now
    )
    assert ready
    assert reason == "main_synced"
    assert retry == 0
    assert fallback == 0


def test_waits_with_ui_retry_when_main_not_yet_completed():
    now = _slot_start(10, 0, 15)
    ready, reason, retry, fallback = s.live_simulation_readiness(
        "2026-07-05T09:45:01", now, poll_sec=15
    )
    assert not ready
    assert reason == "wait_main"
    assert retry == 15
    assert fallback == s.APP_MAIN_SYNC_MAX_WAIT_SECONDS - 15


def test_fallback_after_max_wait_without_main_completion():
    now = _slot_start(10, 0, 30)
    ready, reason, retry, fallback = s.live_simulation_readiness(
        "2026-07-05T09:45:01", now
    )
    assert ready
    assert reason == "fallback"
    assert retry == 0
    assert fallback == 0


def test_ui_retry_capped_by_remaining_fallback():
    now = _slot_start(10, 0, 25)
    ready, reason, retry, fallback = s.live_simulation_readiness(
        "2026-07-05T09:45:01", now, poll_sec=15
    )
    assert not ready
    assert reason == "wait_main"
    assert retry == 5
    assert fallback == 5


def test_sync_ui_countdown_seconds():
    now = _slot_start(10, 0, 10)
    assert s.sync_ui_countdown_seconds("2026-07-05T09:45:01", 15, now) == 15
    assert s.sync_ui_countdown_seconds("2026-07-05T10:00:02", 15, now) == 0


def test_seconds_until_main_py_sync_ready_zero_when_synced():
    now = _slot_start(10, 0, 10)
    assert s.seconds_until_main_py_sync_ready("2026-07-05T10:00:02", now) == 0.0
