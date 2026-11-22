"""Reserve P1 — prompt release of a virtual reserve on appliance start (wait loop)."""
from __future__ import annotations

import pytest

from integrations import ehal_request_http as http_mod
from optimizer import powerstation_live
from optimizer.run_trigger import (
    RESERVE_CHECK_INTERVAL_SEC,
    TRIGGER_RESERVE_RELEASE,
    is_out_of_band_trigger,
    reserve_release_poll,
    wait_until_next_run,
)
from runtime_store import powerstation_reserves as store


@pytest.fixture(autouse=True)
def _clear_optimize_request():
    http_mod.clear_optimize_request()
    yield
    http_mod.clear_optimize_request()


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, sec: float) -> None:
        self.now += sec


def _wait(clock: _FakeClock, poll, total_wait_sec: float = 900.0):
    return wait_until_next_run(
        total_wait_sec=total_wait_sec,
        poll_interval_sec=1.0,
        sleep_fn=clock.sleep,
        on_poll=poll,
        clock_fn=clock,
    )


# --- wait loop ---------------------------------------------------------------


def test_trigger_between_two_ticks_ends_wait_once():
    clock = _FakeClock()
    start = clock.now
    appliance_starts_at = start + 100.0
    checks: list[float] = []
    base_polls: list[float] = []

    def check_release() -> bool:
        checks.append(clock.now)
        return clock.now >= appliance_starts_at

    poll = reserve_release_poll(
        base_poll=lambda: base_polls.append(clock.now),
        check_release=check_release,
        wake_until=start + 900.0 - 60.0,
        clock_fn=clock,
    )
    assert _wait(clock, poll) == TRIGGER_RESERVE_RELEASE
    # Checked every 30 s, not every 1 s chunk; the first tick after the start wakes.
    assert checks == [start + i * RESERVE_CHECK_INTERVAL_SEC for i in range(5)]
    assert clock.now == start + 120.0
    # Base poll (heartbeat, sampler) still runs every chunk.
    assert len(base_polls) == 121


def test_no_wake_inside_early_start_lead():
    clock = _FakeClock()
    start = clock.now
    checks: list[float] = []

    def check_release() -> bool:
        checks.append(clock.now)
        return clock.now >= start + 850.0  # appliance starts 50 s before the run

    poll = reserve_release_poll(
        base_poll=lambda: None,
        check_release=check_release,
        wake_until=start + 900.0 - 60.0,  # lead 60 s
        clock_fn=clock,
    )
    assert _wait(clock, poll) is None
    assert clock.now == pytest.approx(start + 900.0)
    assert checks and max(checks) < start + 840.0


def test_request_optimize_still_wins():
    clock = _FakeClock()

    def base_poll() -> None:
        http_mod.signal_optimize_request()

    poll = reserve_release_poll(
        base_poll=base_poll,
        check_release=lambda: True,
        wake_until=clock.now + 800.0,
        clock_fn=clock,
    )
    assert _wait(clock, poll) == "request_optimize"


def test_stop_fn_ends_wait_without_event():
    clock = _FakeClock()
    fired = http_mod.wait_for_optimize_or_timeout(
        900.0,
        poll_interval_sec=1.0,
        sleep_fn=clock.sleep,
        clock_fn=clock,
        stop_fn=lambda: clock.now >= 1010.0,
    )
    assert fired is False
    assert clock.now == 1010.0


def test_reserve_release_is_out_of_band_and_passes_resolve(monkeypatch):
    from runtime_store.optimization_history import _format_run_trigger_label
    from runtime_store.shadow.hooks import resolve_next_trigger

    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    assert is_out_of_band_trigger(TRIGGER_RESERVE_RELEASE)
    assert (
        resolve_next_trigger(
            TRIGGER_RESERVE_RELEASE, "quarter_hour", optimize_trigger="request_optimize"
        )
        == TRIGGER_RESERVE_RELEASE
    )
    assert _format_run_trigger_label(TRIGGER_RESERVE_RELEASE) == "Reserve-Freigabe"


# --- reserve check -------------------------------------------------------------


@pytest.fixture
def reserve_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "reserves.json"))
    powerstations = [
        {
            "id": "vps",
            "type": "powerstation",
            "backing": "virtual",
            "role": "single_use",
            "battery_capacity_kwh": 5.0,
        }
    ]
    appliances = [
        {
            "id": "waschmaschine",
            "mode": "reserve",
            "powerstation_id": "vps",
            "default_power_kw": 2.0,
            "default_runtime_h": 0.5,
        }
    ]
    monkeypatch.setattr(powerstation_live, "_planning_powerstations", lambda *_a: powerstations)
    monkeypatch.setattr(powerstation_live, "_reserve_appliances", lambda *_a: appliances)
    monkeypatch.setattr(powerstation_live, "_consumers_by_id", lambda *_a: {})
    running = {"waschmaschine": False}
    signal_calls: list[str] = []

    def fake_signal(appliance_id, *, telemetry, consumers_by_id, on_read_error=None):
        assert telemetry is None
        signal_calls.append(appliance_id)
        return running.get(appliance_id, False)

    monkeypatch.setattr(powerstation_live, "appliance_run_signal_active", fake_signal)

    def seed(state: str, stored_kwh: float, *, trigger_active: bool = False) -> None:
        states = store.load_reserve_states()
        entry = store.get_or_init_state(states, "vps", target_kwh=1.0)
        entry["state"] = state
        entry["stored_kwh"] = stored_kwh
        entry["trigger_active"] = trigger_active
        store.save_reserve_states(states)

    return {
        "powerstations": powerstations,
        "running": running,
        "signal_calls": signal_calls,
        "seed": seed,
    }


def test_appliance_start_latches_once(reserve_setup):
    reserve_setup["seed"](store.STATE_STANDBY, 1.0)
    release = powerstation_live.release_virtual_reserves_on_appliance_start

    assert release() == []
    assert store.load_reserve_states()["vps"]["trigger_active"] is False

    reserve_setup["running"]["waschmaschine"] = True
    assert release() == ["vps"]
    entry = store.load_reserve_states()["vps"]
    assert entry["trigger_active"] is True
    assert entry["state"] == store.STATE_DISCHARGING

    # Latched: no second wake while the appliance keeps running.
    calls_before = len(reserve_setup["signal_calls"])
    assert release() == []
    assert len(reserve_setup["signal_calls"]) == calls_before


def test_partly_filled_reserve_releases(reserve_setup):
    reserve_setup["seed"](store.STATE_CHARGING, 0.4)
    reserve_setup["running"]["waschmaschine"] = True
    assert powerstation_live.release_virtual_reserves_on_appliance_start() == ["vps"]


def test_empty_reserve_never_wakes(reserve_setup):
    reserve_setup["seed"](store.STATE_EMPTY, 0.0)
    reserve_setup["running"]["waschmaschine"] = True
    assert powerstation_live.release_virtual_reserves_on_appliance_start() == []
    assert reserve_setup["signal_calls"] == []
    assert store.load_reserve_states()["vps"]["trigger_active"] is False


def test_reserve_without_state_never_wakes(reserve_setup):
    reserve_setup["running"]["waschmaschine"] = True
    assert powerstation_live.release_virtual_reserves_on_appliance_start() == []
    assert reserve_setup["signal_calls"] == []
    # Read-only: the check does not create a state file entry.
    assert store.load_reserve_states() == {}


def test_physical_reserve_is_not_checked(reserve_setup):
    reserve_setup["powerstations"][0]["backing"] = "physical"
    reserve_setup["seed"](store.STATE_STANDBY, 1.0)
    reserve_setup["running"]["waschmaschine"] = True
    assert powerstation_live.release_virtual_reserves_on_appliance_start() == []
    assert reserve_setup["signal_calls"] == []


def test_no_reserve_appliances_never_wakes(monkeypatch):
    monkeypatch.setattr(powerstation_live, "_planning_powerstations", lambda *_a: [])
    monkeypatch.setattr(powerstation_live, "_reserve_appliances", lambda *_a: [])

    def fail_states():
        raise AssertionError("no state read without reserves")

    monkeypatch.setattr(powerstation_live, "load_reserve_states", fail_states)
    assert powerstation_live.release_virtual_reserves_on_appliance_start() == []


def test_wait_loop_with_real_check_wakes_once_per_start(reserve_setup):
    """Two waits in a row: the start wakes the first; the latch keeps the second quiet."""
    reserve_setup["seed"](store.STATE_STANDBY, 1.0)
    clock = _FakeClock()

    def check() -> bool:
        if clock.now >= 1100.0:
            reserve_setup["running"]["waschmaschine"] = True
        return bool(powerstation_live.release_virtual_reserves_on_appliance_start())

    def make_poll():
        return reserve_release_poll(
            base_poll=lambda: None,
            check_release=check,
            wake_until=clock.now + 840.0,
            clock_fn=clock,
        )

    assert _wait(clock, make_poll()) == TRIGGER_RESERVE_RELEASE
    assert _wait(clock, make_poll()) is None
