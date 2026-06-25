"""Tests für Event-Trigger bei E-Auto An-/Abstecken."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from optimizer import charging_trigger as ct


class TestParsePluggedInValue:
    def test_one_is_plugged(self):
        assert ct.parse_plugged_in_value(1) is True
        assert ct.parse_plugged_in_value("1") is True
        assert ct.parse_plugged_in_value(1.0) is True

    def test_zero_is_unplugged(self):
        assert ct.parse_plugged_in_value(0) is False
        assert ct.parse_plugged_in_value("0") is False

    def test_none_on_missing(self):
        assert ct.parse_plugged_in_value(None) is None

    def test_none_on_garbage(self):
        assert ct.parse_plugged_in_value("off") is None


class TestDetectPluggedInEvent:
    def test_no_previous_baseline(self):
        trigger, details = ct.detect_plugged_in_event(None, {"eauto": True})
        assert trigger is None
        assert details == []

    def test_no_change(self):
        trigger, _ = ct.detect_plugged_in_event(
            {"eauto": False},
            {"eauto": False},
        )
        assert trigger is None

    def test_plug_in_detected(self):
        trigger, details = ct.detect_plugged_in_event(
            {"eauto": False},
            {"eauto": True},
        )
        assert trigger == "ev_plugged_in:eauto"
        assert "angeschlossen" in details[0]

    def test_unplug_detected(self):
        trigger, details = ct.detect_plugged_in_event(
            {"eauto": True},
            {"eauto": False},
        )
        assert trigger == "ev_unplugged:eauto"
        assert "nicht angeschlossen" in details[0]

    def test_read_failure_ignored(self):
        trigger, _ = ct.detect_plugged_in_event(
            {"eauto": False},
            {"eauto": None},
        )
        assert trigger is None


class TestPluggedInFromRunState:
    def test_extracts_bool_values(self):
        snapshot = ct.plugged_in_from_run_state(
            {"charging_plugged_in": {"eauto": True, "other": False}}
        )
        assert snapshot == {"eauto": True, "other": False}

    def test_missing_key_returns_empty(self):
        assert ct.plugged_in_from_run_state({}) == {}
        assert ct.plugged_in_from_run_state(None) == {}


class TestWaitUntilNextRun:
    def test_immediate_return_on_zero_wait(self):
        slept: list[float] = []

        def fake_sleep(sec: float) -> None:
            slept.append(sec)

        trigger, snapshot = ct.wait_until_next_run(
            previous_plugged_in={"eauto": False},
            total_wait_sec=0,
            poll_interval_sec=60,
            event_trigger_enabled=True,
            sleep_fn=fake_sleep,
            fetch_snapshot_fn=lambda: {"eauto": True},
        )
        assert trigger is None
        assert snapshot == {"eauto": False}
        assert slept == []

    def test_event_trigger_breaks_wait_early(self):
        slept: list[float] = []
        polls = {"count": 0}

        def fake_sleep(sec: float) -> None:
            slept.append(sec)

        def fake_fetch() -> dict[str, bool | None]:
            polls["count"] += 1
            return {"eauto": True}

        trigger, snapshot = ct.wait_until_next_run(
            previous_plugged_in={"eauto": False},
            total_wait_sec=300,
            poll_interval_sec=60,
            event_trigger_enabled=True,
            sleep_fn=fake_sleep,
            fetch_snapshot_fn=fake_fetch,
        )
        assert trigger == "ev_plugged_in:eauto"
        assert snapshot == {"eauto": True}
        assert slept == [60.0]
        assert polls["count"] == 1

    def test_disabled_waits_full_duration(self):
        slept: list[float] = []

        def fake_sleep(sec: float) -> None:
            slept.append(sec)

        trigger, _ = ct.wait_until_next_run(
            previous_plugged_in={"eauto": False},
            total_wait_sec=120,
            poll_interval_sec=60,
            event_trigger_enabled=False,
            sleep_fn=fake_sleep,
            fetch_snapshot_fn=lambda: {"eauto": True},
        )
        assert trigger is None
        assert slept == [120.0]

    def test_no_monitored_consumers_sleeps_without_poll(self):
        slept: list[float] = []

        def fake_sleep(sec: float) -> None:
            slept.append(sec)

        with patch.object(ct, "consumers_with_plugged_in_signal", return_value=[]):
            trigger, _ = ct.wait_until_next_run(
                previous_plugged_in={},
                total_wait_sec=90,
                poll_interval_sec=30,
                event_trigger_enabled=True,
                sleep_fn=fake_sleep,
                fetch_snapshot_fn=lambda: {"eauto": True},
            )
        assert trigger is None
        assert slept == [90.0]


class TestIsEventTrigger:
    def test_quarter_hour_is_regular(self):
        assert ct.is_event_trigger(ct.TRIGGER_QUARTER_HOUR) is False

    def test_plug_event_is_event(self):
        assert ct.is_event_trigger("ev_plugged_in:eauto") is True
