"""EarlyStart P1 in main.py: plan for the tick, never write before it."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest

import main as main_module
from optimizer import schedule
from optimizer.run_trigger import TRIGGER_QUARTER_HOUR, TRIGGER_REQUEST_OPTIMIZE
from runtime_store.planning_clock import planning_now
from tests.main_run_harness import patch_main_run


def _next_tick() -> datetime:
    return schedule.quarter_hour_slot_start(datetime.now()) + timedelta(minutes=15)


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, sec: float) -> None:
        self.sleeps.append(sec)
        self.t += sec


def test_hold_waits_until_tick_with_polls():
    clock = _FakeClock()
    polls: list[float] = []
    now = datetime(2026, 10, 15, 12, 59, 30)
    main_module._hold_until_tick(
        datetime(2026, 10, 15, 13, 0),
        on_poll=lambda: polls.append(clock.t),
        sleep_fn=clock.sleep,
        clock_fn=clock.monotonic,
        now_fn=lambda: now,
    )
    assert clock.t == pytest.approx(30.0)
    assert len(polls) == 30


def test_hold_after_tick_returns_at_once_and_warns_beyond_90s(caplog):
    clock = _FakeClock()
    tick = datetime(2026, 10, 15, 13, 0)
    with caplog.at_level(logging.INFO, logger="main"):
        main_module._hold_until_tick(
            tick, sleep_fn=clock.sleep, clock_fn=clock.monotonic,
            now_fn=lambda: tick + timedelta(seconds=30),
        )
        main_module._hold_until_tick(
            tick, sleep_fn=clock.sleep, clock_fn=clock.monotonic,
            now_fn=lambda: tick + timedelta(seconds=95),
        )
    assert clock.sleeps == []
    levels = [r.levelno for r in caplog.records if "nach dem Takt fertig" in r.getMessage()]
    assert levels == [logging.INFO, logging.WARNING]


def test_early_cycle_plans_for_tick_and_writes_only_after_hold(monkeypatch):
    patch_main_run(monkeypatch, silent=False)
    tick = _next_tick()
    events: list[str] = []
    seen: dict = {}

    def fake_milp(matrix, current_hour, *a, **k):
        seen["current_hour"] = current_hour
        seen["planning_now"] = planning_now()
        seen["slot_key"] = schedule.quarter_hour_slot_key()
        events.append("solve")
        return (0, 0.0, 99.0, {}, {}, {}, {})

    def fake_hold(t, **_k):
        assert t == tick
        events.append("hold")

    def fake_finalize(start):
        events.append(f"finalize:{start:%H:%M}")
        return {"interval_start": start.isoformat()}

    def fake_write(*_a, **_k):
        events.append("write")
        return []

    monkeypatch.setattr(main_module.optimizer, "milp_optimizer", fake_milp)
    monkeypatch.setattr(main_module, "_hold_until_tick", fake_hold)
    monkeypatch.setattr(
        main_module.power_interval_sampler, "finalize_closed_interval", fake_finalize
    )
    monkeypatch.setattr(
        "optimizer.powerstation_live.write_cycle_powerstation_setpoints", fake_write
    )
    monkeypatch.setattr(main_module.ehal_live, "write_huawei_modbus_states", fake_write)
    monkeypatch.setattr(main_module.ehal_live, "write_flexible_consumer_states", fake_write)
    monkeypatch.setattr(
        main_module.ehal_live,
        "write_inv_ac_limits_from_plan",
        lambda *a, **k: (events.append("write"), (None, []))[1],
    )
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda _p: None)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR, tick=tick, lead_sec=60)

    assert seen["current_hour"] == tick.hour
    assert seen["planning_now"] == tick
    assert seen["slot_key"] == tick.strftime("%Y-%m-%dT%H:%M")
    previous = (tick - timedelta(minutes=15)).strftime("%H:%M")
    assert events[:3] == ["solve", "hold", f"finalize:{previous}"]
    assert events.count("write") >= 1
    assert "finalize" not in " ".join(events[: events.index("hold")])


def test_regular_cycle_without_tick_does_not_hold(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
    monkeypatch.setattr(
        main_module, "_hold_until_tick",
        lambda *_a, **_k: pytest.fail("no hold without early start"),
    )
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda _p: None)
    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)


def test_out_of_band_run_rejects_tick():
    with pytest.raises(ValueError, match="Out-of-band"):
        main_module.main(run_trigger=TRIGGER_REQUEST_OPTIMIZE, tick=_next_tick())
