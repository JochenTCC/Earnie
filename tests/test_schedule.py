"""Tests für Viertelstunden-Takt und main.py-Synchronisation."""
from __future__ import annotations

from datetime import datetime, timedelta

from optimizer import schedule as s


def _slot_start(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 7, 5, hour, minute, second)


def test_ready_immediately_when_main_completed_in_current_slot():
    now = _slot_start(10, 0, 5)
    ready, reason, retry, sync_wait, fresh = s.live_simulation_readiness(
        "2026-07-05T10:00:01", now
    )
    assert ready
    assert reason == "main_synced"
    assert retry == 0
    assert sync_wait == 0
    assert fresh is True


def test_waits_with_ui_retry_when_main_not_yet_completed():
    now = _slot_start(10, 0, 15)
    ready, reason, retry, sync_wait, fresh = s.live_simulation_readiness(
        "2026-07-05T09:45:01", now, poll_sec=15
    )
    assert not ready
    assert reason == "wait_main"
    assert retry == 15
    assert sync_wait == s.APP_MAIN_SYNC_MAX_WAIT_SECONDS - 15
    assert fresh is True


def test_main_down_after_max_wait_without_main_completion():
    now = _slot_start(10, 0, 30)
    ready, reason, retry, sync_wait, fresh = s.live_simulation_readiness(
        "2026-07-05T09:45:01", now
    )
    assert ready
    assert reason == "main_down"
    assert retry == 0
    assert sync_wait == 0
    assert fresh is True


def test_main_down_with_persisted_fresh_snapshot():
    now = _slot_start(10, 0, 30)
    persisted = (now - timedelta(minutes=30)).isoformat(timespec="seconds")
    ready, reason, _, _, fresh = s.live_simulation_readiness(
        "2026-07-05T09:45:01",
        now,
        persisted_completed_at=persisted,
    )
    assert ready
    assert reason == "main_down"
    assert fresh is True


def test_main_down_with_persisted_stale_snapshot():
    now = _slot_start(10, 0, 30)
    persisted = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    ready, reason, _, _, fresh = s.live_simulation_readiness(
        "2026-07-05T09:45:01",
        now,
        persisted_completed_at=persisted,
    )
    assert ready
    assert reason == "main_down"
    assert fresh is False


def test_main_down_without_any_completed_at():
    now = _slot_start(10, 0, 30)
    ready, reason, _, _, fresh = s.live_simulation_readiness(None, now)
    assert ready
    assert reason == "main_down"
    assert fresh is False


def test_ui_retry_capped_by_remaining_sync_wait():
    now = _slot_start(10, 0, 25)
    ready, reason, retry, sync_wait, _ = s.live_simulation_readiness(
        "2026-07-05T09:45:01", now, poll_sec=15
    )
    assert not ready
    assert reason == "wait_main"
    assert retry == 5
    assert sync_wait == 5


def test_sync_ui_countdown_seconds():
    now = _slot_start(10, 0, 10)
    assert s.sync_ui_countdown_seconds("2026-07-05T09:45:01", 15, now) == 15
    assert s.sync_ui_countdown_seconds("2026-07-05T10:00:02", 15, now) == 0


def test_seconds_until_main_py_sync_ready_zero_when_synced():
    now = _slot_start(10, 0, 10)
    assert s.seconds_until_main_py_sync_ready("2026-07-05T10:00:02", now) == 0.0


def test_persisted_display_freshness_boundary():
    now = _slot_start(10, 0, 0)
    fresh_ts = (now - timedelta(minutes=59)).isoformat(timespec="seconds")
    stale_ts = (now - timedelta(minutes=61)).isoformat(timespec="seconds")
    assert s.is_persisted_display_fresh(fresh_ts, now)
    assert not s.is_persisted_display_fresh(stale_ts, now)
