"""Tests für konfigurierbare Loxone-Event-Trigger."""
from __future__ import annotations

from optimizer import event_trigger as et


BINARY_PLUG = {
    "id": "eauto_plugged_in",
    "loxone_name": "Ernie_EAuto_Da",
    "signal_type": "binary",
    "on_change": "any",
    "label": "E-Auto angeschlossen",
}

BINARY_RISING = {
    **BINARY_PLUG,
    "on_change": "rising",
}

TEXT_READY = {
    "id": "eauto_ready_by",
    "loxone_name": "Ernie_EAuto_FertigUm",
    "signal_type": "text",
    "on_change": "any",
    "label": "E-Auto Fertig-Uhrzeit",
}


TEXT_READY = {
    "id": "eauto_ready_by",
    "loxone_name": "Ernie_EAuto_FertigUm",
    "signal_type": "text",
    "on_change": "any",
    "label": "E-Auto Fertig-Uhrzeit",
}

ANALOG_SOC = {
    "id": "eauto_rest_soc",
    "loxone_name": "Rest-SOC",
    "signal_type": "analog",
    "on_change": "any",
    "label": "E-Auto Rest-SOC",
}


class TestParseAnalogValue:
    def test_percent_value(self):
        assert et.parse_analog_value(42.5) == 42.5
        assert et.parse_analog_value(42) == 42.0

    def test_none_on_garbage(self):
        assert et.parse_analog_value("off") is None


class TestDetectTriggerEventAnalog:
    def test_rest_soc_change(self):
        trigger, details = et.detect_trigger_event(
            {"eauto_rest_soc": 20.0},
            {"eauto_rest_soc": 35.0},
            [ANALOG_SOC],
        )
        assert trigger == "event:eauto_rest_soc"
        assert "Rest-SOC" in details[0]

    def test_rest_soc_unchanged(self):
        trigger, _ = et.detect_trigger_event(
            {"eauto_rest_soc": 35.0},
            {"eauto_rest_soc": 35.0},
            [ANALOG_SOC],
        )
        assert trigger is None


class TestParseBinaryValue:
    def test_one_is_true(self):
        assert et.parse_binary_value(1) is True
        assert et.parse_binary_value("1") is True

    def test_zero_is_false(self):
        assert et.parse_binary_value(0) is False

    def test_none_on_missing(self):
        assert et.parse_binary_value(None) is None


class TestParseTextValue:
    def test_strips_text(self):
        assert et.parse_text_value("  Morgen, 07:00  ") == "Morgen, 07:00"

    def test_empty_is_none(self):
        assert et.parse_text_value("") is None
        assert et.parse_text_value("   ") is None


class TestDetectTriggerEvent:
    def test_no_previous_baseline(self):
        trigger, details = et.detect_trigger_event(None, {"eauto_plugged_in": True}, [BINARY_PLUG])
        assert trigger is None
        assert details == []

    def test_binary_any_change(self):
        trigger, details = et.detect_trigger_event(
            {"eauto_plugged_in": False},
            {"eauto_plugged_in": True},
            [BINARY_PLUG],
        )
        assert trigger == "event:eauto_plugged_in"
        assert "E-Auto angeschlossen" in details[0]

    def test_binary_rising_only(self):
        trigger, _ = et.detect_trigger_event(
            {"eauto_plugged_in": True},
            {"eauto_plugged_in": False},
            [BINARY_RISING],
        )
        assert trigger is None

    def test_text_change(self):
        trigger, details = et.detect_trigger_event(
            {"eauto_ready_by": "Heute, 22:00"},
            {"eauto_ready_by": "Morgen, 07:00"},
            [TEXT_READY],
        )
        assert trigger == "event:eauto_ready_by"
        assert "Fertig-Uhrzeit" in details[0]

    def test_text_no_change(self):
        trigger, _ = et.detect_trigger_event(
            {"eauto_ready_by": "Morgen, 07:00"},
            {"eauto_ready_by": "Morgen, 07:00"},
            [TEXT_READY],
        )
        assert trigger is None


class TestSnapshotFromRunState:
    def test_reads_event_trigger_snapshot(self):
        snapshot = et.snapshot_from_run_state(
            {"event_trigger_snapshot": {"eauto_plugged_in": True}}
        )
        assert snapshot == {"eauto_plugged_in": True}

    def test_legacy_charging_plugged_in(self):
        snapshot = et.snapshot_from_run_state(
            {"charging_plugged_in": {"eauto": True}}
        )
        assert snapshot == {"eauto": True}


class TestWaitUntilNextRun:
    def test_event_trigger_breaks_wait_early(self):
        slept: list[float] = []

        def fake_sleep(sec: float) -> None:
            slept.append(sec)

        trigger, snapshot = et.wait_until_next_run(
            previous_snapshot={"eauto_plugged_in": False},
            trigger_specs=[BINARY_PLUG],
            total_wait_sec=300,
            poll_interval_sec=60,
            event_trigger_enabled=True,
            sleep_fn=fake_sleep,
            fetch_snapshot_fn=lambda: {"eauto_plugged_in": True},
        )
        assert trigger == "event:eauto_plugged_in"
        assert snapshot == {"eauto_plugged_in": True}
        assert slept == [60.0]

    def test_no_specs_sleeps_full_duration(self):
        slept: list[float] = []

        def fake_sleep(sec: float) -> None:
            slept.append(sec)

        trigger, _ = et.wait_until_next_run(
            previous_snapshot={},
            trigger_specs=[],
            total_wait_sec=90,
            poll_interval_sec=30,
            event_trigger_enabled=True,
            sleep_fn=fake_sleep,
            fetch_snapshot_fn=lambda: {"eauto_plugged_in": True},
        )
        assert trigger is None
        assert slept == [90.0]


class TestBuildRunTrigger:
    def test_event_prefix(self):
        assert et.build_run_trigger("eauto_plugged_in") == "event:eauto_plugged_in"

    def test_is_event_trigger(self):
        assert et.is_event_trigger(et.TRIGGER_QUARTER_HOUR) is False
        assert et.is_event_trigger("event:eauto_plugged_in") is True
