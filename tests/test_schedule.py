"""Tests für Viertelstunden-Takt und main.py-Synchronisation."""
from __future__ import annotations

from datetime import datetime

from optimizer import schedule as s


def _slot_start(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 7, 5, hour, minute, second)


def test_ready_immediately_when_main_completed_in_current_slot():
    now = _slot_start(10, 0, 5)
    ready, reason, wait = s.live_simulation_readiness("2026-07-05T10:00:01", now)
    assert ready
    assert reason == "main_synced"
    assert wait == 0


def test_waits_with_unified_countdown_when_main_not_yet_completed():
    now = _slot_start(10, 0, 30)
    ready, reason, wait = s.live_simulation_readiness("2026-07-05T09:45:01", now)
    assert not ready
    assert reason == "wait_main"
    assert wait == s.APP_MAIN_SYNC_MAX_WAIT_SECONDS - 30


def test_fallback_after_max_wait_without_main_completion():
    now = _slot_start(10, 1, 30)
    ready, reason, wait = s.live_simulation_readiness("2026-07-05T09:45:01", now)
    assert ready
    assert reason == "fallback"
    assert wait == 0


def test_initial_wait_phase_countdown():
    now = _slot_start(10, 0, 20)
    ready, reason, wait = s.live_simulation_readiness("2026-07-05T09:45:01", now)
    assert not ready
    assert reason == "wait_main"
    assert wait == s.APP_MAIN_SYNC_MAX_WAIT_SECONDS - 20


def test_extra_grace_phase_after_initial_wait():
    now = _slot_start(10, 1, 10)
    ready, reason, wait = s.live_simulation_readiness("2026-07-05T09:45:01", now)
    assert not ready
    assert reason == "wait_main"
    assert wait == s.APP_MAIN_SYNC_MAX_WAIT_SECONDS - 70


def test_seconds_until_main_py_sync_ready_zero_when_synced():
    now = _slot_start(10, 0, 10)
    assert s.seconds_until_main_py_sync_ready("2026-07-05T10:00:02", now) == 0.0
