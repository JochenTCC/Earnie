"""Planning clock: an early-started cycle plans as if it were the tick."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from optimizer import schedule
from runtime_store.planning_clock import anchored_tick, planning_anchor, planning_now


def _next_tick() -> datetime:
    return schedule.quarter_hour_slot_start(datetime.now()) + timedelta(minutes=15)


def test_without_anchor_is_real_time():
    before = datetime.now()
    assert before <= planning_now() <= datetime.now()
    assert anchored_tick() is None


def test_anchor_in_future_freezes_planning_now_at_tick():
    tick = _next_tick()
    with planning_anchor(tick):
        assert planning_now() == tick
        assert anchored_tick() == tick
        assert schedule.quarter_hour_slot_start() == tick
        assert schedule.quarter_hour_slot_key() == tick.strftime("%Y-%m-%dT%H:%M")
    assert planning_now() < tick


def test_anchor_respects_requested_timezone():
    tick = _next_tick()
    tz = ZoneInfo("Europe/Vienna")
    with planning_anchor(tick):
        aware = planning_now(tz)
    assert aware.tzinfo is not None
    assert aware == tick.astimezone(tz)


def test_anchor_in_past_returns_real_time():
    tick = schedule.quarter_hour_slot_start(datetime.now()) - timedelta(minutes=15)
    with planning_anchor(tick):
        now = planning_now()
    assert now > tick + timedelta(minutes=14)


def test_none_anchor_keeps_real_clock():
    with planning_anchor(None):
        assert anchored_tick() is None
        assert abs((planning_now() - datetime.now()).total_seconds()) < 1
