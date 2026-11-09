"""Dynamic EV ↔ wallbox state machine (multi-EV M3, D4–D7)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from optimizer.ev_assignment import (
    EVIDENCE_PLUG_MATCH,
    EVIDENCE_TEST_CHARGE,
    EVIDENCE_USER_PICK,
    STATUS_ASSIGNED,
    STATUS_FREE,
    STATUS_PLUGGED_UNKNOWN,
    STATUS_TESTING,
    AssignmentEngine,
    AssignmentSettings,
    EvObservation,
    EvSpec,
    Pick,
    ProbeWrite,
    WallboxSpec,
)

T0 = datetime(2026, 11, 9, 18, 0, 0)
SETTINGS = AssignmentSettings(
    poll_sec=10.0, match_window_sec=300.0, test_duration_sec=120.0, test_power_threshold_w=500.0
)


def _engine(*, sensors: dict[str, tuple[bool, bool]] | None = None) -> AssignmentEngine:
    """Two wallboxes, three dynamic cars allowed at both; sensors = (plug, power)."""
    sensors = sensors or {"car_a": (True, True), "car_b": (True, True), "car_c": (False, False)}
    return AssignmentEngine(
        [WallboxSpec("wb_1", 6.0), WallboxSpec("wb_2", 6.0)],
        [
            EvSpec(ev, ("wb_1", "wb_2"), has_plug_sensor=plug, has_power_sensor=power)
            for ev, (plug, power) in sensors.items()
        ],
        SETTINGS,
    )


def _ev(plugged=None, power=None, immediate=False) -> EvObservation:
    return EvObservation(plugged=plugged, power_w=power, immediate=immediate)


def _idle(engine: AssignmentEngine, at: datetime) -> None:
    """First observation: nothing plugged, every car with a plug sensor reports unplugged."""
    engine.step(
        at,
        {"wb_1": False, "wb_2": False},
        {"car_a": _ev(False, 0.0), "car_b": _ev(False, 0.0), "car_c": _ev()},
    )


def test_plug_match_assigns_after_the_window() -> None:
    engine = _engine()
    _idle(engine, T0)
    t1 = T0 + timedelta(seconds=10)
    cars = {"car_a": _ev(False, 0.0), "car_b": _ev(False, 0.0), "car_c": _ev()}
    engine.step(t1, {"wb_1": True, "wb_2": False}, cars)
    assert engine.states["wb_1"].status == STATUS_PLUGGED_UNKNOWN
    t2 = t1 + timedelta(seconds=60)
    cars["car_a"] = _ev(True, 0.0)
    engine.step(t2, {"wb_1": True, "wb_2": False}, cars)
    # Decided only after the window: another car could still report.
    assert engine.states["wb_1"].status == STATUS_PLUGGED_UNKNOWN
    result = engine.step(t1 + timedelta(seconds=301), {"wb_1": True, "wb_2": False}, cars)
    state = engine.states["wb_1"]
    assert (state.status, state.ev_id, state.evidence) == (
        STATUS_ASSIGNED,
        "car_a",
        EVIDENCE_PLUG_MATCH,
    )
    assert result.assignment_changed
    assert engine.assignments() == {"car_a": "wb_1"}


def test_two_wallboxes_plugged_together_go_to_the_test_charge() -> None:
    engine = _engine()
    _idle(engine, T0)
    t1 = T0 + timedelta(seconds=10)
    cars = {"car_a": _ev(True, 0.0), "car_b": _ev(False, 0.0), "car_c": _ev()}
    engine.step(t1, {"wb_1": True, "wb_2": True}, cars)
    result = engine.step(t1 + timedelta(seconds=301), {"wb_1": True, "wb_2": True}, cars)
    # car_a's edge fits both wallboxes: no plug match; one test at a time.
    assert engine.states["wb_1"].status == STATUS_TESTING
    assert engine.states["wb_2"].status == STATUS_PLUGGED_UNKNOWN
    assert result.writes == [ProbeWrite("wb_1", 6.0)]
    cars["car_a"] = _ev(True, 1380.0)
    result = engine.step(t1 + timedelta(seconds=320), {"wb_1": True, "wb_2": True}, cars)
    assert engine.states["wb_1"].ev_id == "car_a"
    assert engine.states["wb_1"].evidence == EVIDENCE_TEST_CHARGE
    assert ProbeWrite("wb_1", 0.0) in result.writes
    # wb_2: car_a is taken, car_b reports unplugged; car_c has no sensor → user pick.
    assert engine.candidates("wb_2", cars) == ["car_c"]
    assert engine.states["wb_2"].status == STATUS_PLUGGED_UNKNOWN
    assert "Probeladung nicht möglich" in engine.states["wb_2"].note


def test_test_charge_without_reaction_waits_for_the_user() -> None:
    engine = _engine()
    _idle(engine, T0)
    t1 = T0 + timedelta(seconds=10)
    cars = {"car_a": _ev(False, 0.0), "car_b": _ev(False, 0.0), "car_c": _ev()}
    engine.step(t1, {"wb_1": True, "wb_2": False}, cars)
    engine.step(t1 + timedelta(seconds=301), {"wb_1": True, "wb_2": False}, cars)
    # Only car_c (no sensors) is a candidate: no test possible.
    state = engine.states["wb_1"]
    assert state.status == STATUS_PLUGGED_UNKNOWN
    assert "Probeladung nicht möglich" in state.note
    assert engine.candidates("wb_1", cars) == ["car_c"]
    result = engine.step(
        t1 + timedelta(seconds=400),
        {"wb_1": True, "wb_2": False},
        cars,
        [Pick("wb_1", "car_c", state.session)],
    )
    assert engine.states["wb_1"].evidence == EVIDENCE_USER_PICK
    assert result.assignment_changed


def test_test_charge_times_out() -> None:
    engine = _engine(sensors={"car_a": (False, True), "car_b": (False, True)})
    engine.step(T0, {"wb_1": True, "wb_2": False}, {})
    assert engine.states["wb_1"].status == STATUS_TESTING
    cars = {"car_a": _ev(power=0.0), "car_b": _ev(power=0.0)}
    engine.step(T0 + timedelta(seconds=119), {"wb_1": True, "wb_2": False}, cars)
    assert engine.states["wb_1"].status == STATUS_TESTING
    result = engine.step(T0 + timedelta(seconds=120), {"wb_1": True, "wb_2": False}, cars)
    assert engine.states["wb_1"].status == STATUS_PLUGGED_UNKNOWN
    assert engine.states["wb_1"].note == "Probeladung: kein Auto hat reagiert"
    assert result.writes == [ProbeWrite("wb_1", 0.0)]
    # No second test in the same plug session.
    result = engine.step(T0 + timedelta(seconds=200), {"wb_1": True, "wb_2": False}, cars)
    assert result.writes == []


def test_ambiguous_test_charge_is_no_evidence() -> None:
    engine = _engine(sensors={"car_a": (False, True), "car_b": (False, True)})
    engine.step(T0, {"wb_1": True, "wb_2": False}, {})
    cars = {"car_a": _ev(power=1400.0), "car_b": _ev(power=1400.0)}
    engine.step(T0 + timedelta(seconds=20), {"wb_1": True, "wb_2": False}, cars)
    assert engine.states["wb_1"].status == STATUS_PLUGGED_UNKNOWN
    assert "mehrdeutig" in engine.states["wb_1"].note
    assert engine.assignments() == {}


def test_restart_starts_without_plug_edge() -> None:
    """D7: on start a plugged wallbox has no edge, so the ladder begins with the test."""
    engine = _engine()
    cars = {"car_a": _ev(True, 0.0), "car_b": _ev(False, 0.0), "car_c": _ev()}
    result = engine.step(T0, {"wb_1": True, "wb_2": False}, cars)
    state = engine.states["wb_1"]
    assert state.plugged_at is None
    assert state.status == STATUS_TESTING
    assert state.test_candidates == ("car_a", "car_c")
    assert result.writes == [ProbeWrite("wb_1", 6.0)]


def test_unplug_frees_the_wallbox_and_stops_a_test() -> None:
    engine = _engine(sensors={"car_a": (False, True)})
    engine.step(T0, {"wb_1": True, "wb_2": False}, {})
    assert engine.states["wb_1"].status == STATUS_TESTING
    result = engine.step(T0 + timedelta(seconds=5), {"wb_1": False, "wb_2": False}, {})
    assert engine.states["wb_1"].status == STATUS_FREE
    assert result.writes == [ProbeWrite("wb_1", 0.0)]


def test_unplug_ends_an_assignment() -> None:
    engine = _engine(sensors={"car_a": (False, True)})
    engine.step(T0, {"wb_1": True, "wb_2": False}, {})
    engine.step(T0 + timedelta(seconds=10), {"wb_1": True, "wb_2": False}, {"car_a": _ev(power=900.0)})
    assert engine.assignments() == {"car_a": "wb_1"}
    result = engine.step(T0 + timedelta(seconds=20), {"wb_1": False, "wb_2": False}, {})
    assert engine.assignments() == {}
    assert result.assignment_changed


def test_test_charge_skipped_during_immediate_charge() -> None:
    engine = _engine(sensors={"car_a": (False, True)})
    result = engine.step(
        T0, {"wb_1": True, "wb_2": False}, {"car_a": _ev(immediate=True)}
    )
    assert engine.states["wb_1"].status == STATUS_PLUGGED_UNKNOWN
    assert engine.states["wb_1"].note == "Probeladung ausgesetzt (Sofort laden)"
    assert result.writes == []
    # Once "Sofort laden" ends the test runs.
    result = engine.step(T0 + timedelta(seconds=10), {"wb_1": True, "wb_2": False}, {})
    assert engine.states["wb_1"].status == STATUS_TESTING


def test_no_test_charge_when_setpoints_are_not_written() -> None:
    engine = _engine(sensors={"car_a": (False, True)})
    result = engine.step(T0, {"wb_1": True, "wb_2": False}, {}, allow_test=False)
    assert engine.states["wb_1"].status == STATUS_PLUGGED_UNKNOWN
    assert "Sollwerte werden nicht gesendet" in engine.states["wb_1"].note
    assert result.writes == []


def test_pick_for_an_old_plug_session_is_ignored() -> None:
    engine = _engine(sensors={"car_a": (False, False)})
    engine.step(T0, {"wb_1": True, "wb_2": False}, {})
    old = engine.states["wb_1"].session
    engine.step(T0 + timedelta(seconds=5), {"wb_1": False, "wb_2": False}, {})
    engine.step(T0 + timedelta(seconds=10), {"wb_1": True, "wb_2": False}, {})
    engine.step(
        T0 + timedelta(seconds=15),
        {"wb_1": True, "wb_2": False},
        {},
        [Pick("wb_1", "car_a", old)],
    )
    assert engine.assignments() == {}


def test_user_pick_moves_a_car_assigned_elsewhere() -> None:
    engine = _engine(sensors={"car_a": (False, False), "car_b": (False, False)})
    engine.step(T0, {"wb_1": True, "wb_2": True}, {})
    s1, s2 = engine.states["wb_1"].session, engine.states["wb_2"].session
    engine.step(T0, {"wb_1": True, "wb_2": True}, {}, [Pick("wb_1", "car_a", s1)])
    engine.step(T0, {"wb_1": True, "wb_2": True}, {}, [Pick("wb_2", "car_a", s2)])
    assert engine.assignments() == {"car_a": "wb_2"}
    assert engine.states["wb_1"].status == STATUS_PLUGGED_UNKNOWN


def test_car_reporting_unplugged_is_no_candidate() -> None:
    engine = _engine()
    cars = {"car_a": _ev(False, 0.0), "car_b": _ev(True, 0.0), "car_c": _ev()}
    assert engine.candidates("wb_1", cars) == ["car_b", "car_c"]


def test_unknown_wallbox_in_ev_spec_raises() -> None:
    with pytest.raises(ValueError, match="unbekannte Wallbox"):
        AssignmentEngine([WallboxSpec("wb_1", 6.0)], [EvSpec("car_a", ("wb_9",), True, True)])
