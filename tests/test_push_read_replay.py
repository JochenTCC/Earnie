"""Cycle recorder: capture push-inbox reads live, serve them in replay."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from runtime_store import ehal_push_inbox as inbox
from runtime_store.push_read_replay import (
    close_push_read_capture,
    open_push_read_capture,
    replay_push_reads,
)

_PLUGGED = "evcs.e_auto.sens_evcs_connected"
_READY = "ev.e_auto.get_evcs_ready_by_time"
_COUNTER = "sens_pv_energy"


@pytest.fixture(autouse=True)
def _runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
    close_push_read_capture()
    yield
    close_push_read_capture()
    inbox.reset_memory_for_tests()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_capture_keeps_the_first_result_of_each_read_kind():
    now = _now()
    inbox.record_push(_PLUGGED, "1", now=now)
    inbox.record_push(_READY, "1735689600", now=now)
    inbox.record_push(_COUNTER, "24120.12", now=now)
    open_push_read_capture()
    first = inbox.read_push_value(_PLUGGED, now=now)
    inbox.record_push(_PLUGGED, "0", now=now)
    inbox.read_push_value(_PLUGGED, now=now)
    inbox.read_push_ready_by_time(_READY, now=now)
    inbox.read_push_counter(_COUNTER, now=now)
    bucket = close_push_read_capture()

    assert bucket["value"][_PLUGGED] == [first[0], first[1]]
    assert first[0] == pytest.approx(1.0)
    assert bucket["ready_by_time"][_READY] == pytest.approx(1735689600.0)
    assert bucket["counter"][_COUNTER] == pytest.approx(24120.12)


def test_reads_outside_a_capture_are_not_stored():
    inbox.record_push(_PLUGGED, "1", now=_now())
    inbox.read_push_value(_PLUGGED, now=_now())
    assert close_push_read_capture() is None


def test_replay_serves_recorded_reads_instead_of_the_inbox():
    inbox.record_push(_PLUGGED, "0", now=_now())
    recorded = {
        "value": {_PLUGGED: [1.0, inbox.STATE_OK]},
        "ready_by_time": {_READY: "Morgen, 07:00"},
        "counter": {_COUNTER: 5.5},
    }
    with replay_push_reads(recorded):
        assert inbox.read_push_value(_PLUGGED) == (1.0, inbox.STATE_OK)
        assert inbox.read_push_ready_by_time(_READY) == "Morgen, 07:00"
        assert inbox.read_push_counter(_COUNTER) == 5.5
    assert inbox.read_push_value(_PLUGGED, now=_now())[0] == pytest.approx(0.0)


def test_replay_fails_loud_on_a_read_the_live_cycle_did_not_make():
    with replay_push_reads({"value": {}}):
        with pytest.raises(ValueError, match="not recorded"):
            inbox.read_push_value(_PLUGGED)


def test_replay_serves_a_recorded_none():
    with replay_push_reads({"value": {_PLUGGED: [None, inbox.STATE_READ_ERROR]}}):
        assert inbox.read_push_value(_PLUGGED) == (None, inbox.STATE_READ_ERROR)


def test_replay_rejects_a_non_dict_record():
    with pytest.raises(TypeError, match="push_reads"):
        with replay_push_reads(["not", "a", "dict"]):
            pass
