"""Review fixes of the Reserve epic (2026-11-22), findings 1 to 5.

Spec: ``docs/dev/virtual-reserve-price-aware.md`` (§ 1 Prompt release, § 2 Price-aware floor).

1. P2: the persisted fill basis counts the hold from now (slot 0), not from the fill time.
2. P1: a run that ends after the tick of a slot it did not plan is followed by a regular run.
3. P2: a start below ``min_soc`` cannot skip the reserve floor by never setting ``recovered``.
4. P2: fill-slot times are validated before the model; the basis is persisted after the writes.
5. P1: failed live reads in the wait-loop check are logged (once per source and wait).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest

from optimizer import powerstation_live
from optimizer.reserve_price_floor import reserve_price_floor
from optimizer.start_scheduler import missed_slot_start
from tests.test_reserve_price_floor import (
    _BASE_SOC,
    _DT_H,
    _FLOOR_SOC,
    _RESERVE_KWH,
    _SOC_TOL,
    _START,
    _matrix,
    _prepared,
    _reserve,
    _schedule,
    _soc,
)


def _matrix_from(start: datetime, prices: list[float]) -> list[dict]:
    rows = _matrix(prices)
    shift = start - _START
    for row in rows:
        dt = row["slot_datetime"] + shift
        row.update({"slot_datetime": dt, "hour": dt.hour, "date": dt.date()})
    return rows


@pytest.fixture
def store(tmp_path, monkeypatch):
    from runtime_store import powerstation_reserves as store

    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "reserves.json"))
    states = store.load_reserve_states()
    entry = store.get_or_init_state(states, "vps", target_kwh=_RESERVE_KWH)
    entry["state"] = store.STATE_STANDBY
    entry["stored_kwh"] = _RESERVE_KWH
    store.save_reserve_states(states)
    return store


# --- finding 1: sunk hold time of the fill basis -----------------------------------------------

# Review scenario: 15 kWh, eff 0.95, drain 0.15 kW, 1.1 kWh reserve, basis 25 ct, phase 35 ct.
_DRAIN = {"efficiency": 0.95, "idle_drain_kw": 0.15}


def test_long_flat_expensive_phase_keeps_the_floor_over_consecutive_cycles(store) -> None:
    """Re-plans every 15 min for 4 h of a flat 35-ct phase with the basis read back each cycle.

    Counting the hold from the fill time dropped the floor after about 2 h and cleared the
    basis; the energy then counted as free in the middle of the phase.
    """
    from optimizer.powerstation_live import update_reserve_fill_basis

    fill_at = _START
    states = store.load_reserve_states()
    store.set_fill_basis(states["vps"], price=25.0, at=fill_at)
    store.save_reserve_states(states)
    for cycle in range(17):
        entry = store.load_reserve_states()["vps"]
        assert entry["fill_basis_price"] == pytest.approx(25.0), f"basis lost at cycle {cycle}"
        basis = (entry["fill_basis_price"], datetime.fromisoformat(entry["fill_basis_at"]))
        reserve = _reserve(basis=basis)
        battery = _prepared(reserve, **_DRAIN)
        matrix = _matrix_from(_START + timedelta(minutes=15 * cycle), [35.0] * 16)
        plan = reserve_price_floor(battery, matrix, horizon=16, dt_h=_DT_H)
        assert plan.held_now, f"floor dropped {cycle * 15} min after filling"
        update_reserve_fill_basis(battery, matrix, [reserve], dt_h=_DT_H)
    # the basis keeps its original fill time (when the energy was bought)
    assert datetime.fromisoformat(store.load_reserve_states()["vps"]["fill_basis_at"]) == fill_at


def test_basis_hold_counts_from_slot_0_not_from_the_fill_time() -> None:
    reserve = _reserve(basis=(25.0, _START - timedelta(hours=6)))
    plan = reserve_price_floor(
        _prepared(reserve, **_DRAIN), _matrix([35.0] * 16), horizon=16, dt_h=_DT_H
    )
    # 6 h of past hold would cost more than 35 ct; from now on the first slots still pay
    assert plan.pays[0]
    assert plan.fill_price[0] == pytest.approx(25.0)
    # the hold from now still grows: a long horizon stops paying eventually
    assert not all(plan.pays)


def test_milp_holds_the_reserve_hours_after_filling_with_drain() -> None:
    reserve = _reserve(basis=(25.0, _START - timedelta(hours=3)))
    schedule = _schedule(_matrix([35.0] * 4), 20.0, _prepared(reserve, **_DRAIN))
    assert min(_soc(schedule)) >= _FLOOR_SOC - _SOC_TOL


# --- finding 2: release run across the tick ----------------------------------------------------


def test_release_run_that_ends_after_the_tick_is_followed_at_once() -> None:
    started = datetime(2026, 11, 22, 10, 14, 40)
    assert missed_slot_start(started, None, datetime(2026, 11, 22, 10, 15, 35)) == datetime(
        2026, 11, 22, 10, 15
    )


def test_release_run_that_ends_before_the_tick_waits_for_it() -> None:
    started = datetime(2026, 11, 22, 10, 13, 0)
    assert missed_slot_start(started, None, datetime(2026, 11, 22, 10, 14, 10)) is None


def test_early_started_run_for_the_tick_needs_no_catch_up() -> None:
    tick = datetime(2026, 11, 22, 10, 15)
    started = datetime(2026, 11, 22, 10, 14, 0)
    assert missed_slot_start(started, tick, datetime(2026, 11, 22, 10, 15, 20)) is None


def test_overlong_regular_run_misses_the_next_tick() -> None:
    started = datetime(2026, 11, 22, 10, 15, 0)
    assert missed_slot_start(started, None, datetime(2026, 11, 22, 10, 30, 5)) == datetime(
        2026, 11, 22, 10, 30
    )


# --- finding 3: start below min_soc ------------------------------------------------------------


def test_start_below_min_soc_still_builds_the_reserve_for_the_paying_slots() -> None:
    """Without a forced ``recovered`` the solver left the battery at 3 % and skipped the floor."""
    prices = [20.0] * 8 + [35.0] * 8
    schedule = _schedule(_matrix(prices), 3.0, _prepared(_reserve(state="empty")))
    soc = _soc(schedule)
    assert soc[7] >= _FLOOR_SOC - _SOC_TOL, "reserve not built before the first paying slot"
    assert all(s >= _FLOOR_SOC - _SOC_TOL for s in soc[7:])


def test_start_below_min_soc_without_a_paying_slot_is_not_forced_up() -> None:
    schedule = _schedule(_matrix([30.0] * 16), 3.0, _prepared(_reserve(state="empty")))
    assert max(_soc(schedule)) <= _BASE_SOC + _SOC_TOL


# --- finding 4: fill-slot times and the order of the basis update --------------------------------


def test_fill_slot_without_a_time_fails_before_the_model() -> None:
    matrix = _matrix([20.0] + [35.0] * 7)
    del matrix[0]["slot_datetime"]
    with pytest.raises(ValueError, match="slot_datetime"):
        reserve_price_floor(_prepared(), matrix, horizon=8, dt_h=_DT_H)


def test_fill_slot_with_a_naive_time_fails_before_the_model() -> None:
    matrix = _matrix([20.0] + [35.0] * 7)
    matrix[0]["slot_datetime"] = matrix[0]["slot_datetime"].replace(tzinfo=None)
    with pytest.raises(ValueError, match="Zeitzone"):
        reserve_price_floor(_prepared(), matrix, horizon=8, dt_h=_DT_H)


def test_basis_update_failure_comes_after_the_setpoint_writes(monkeypatch) -> None:
    import main as main_module
    from optimizer.run_trigger import TRIGGER_QUARTER_HOUR
    from tests.main_run_harness import patch_main_run

    patch_main_run(monkeypatch, silent=False)
    order: list[str] = []
    monkeypatch.setattr(
        main_module.ehal_live,
        "write_huawei_modbus_states",
        lambda *a, **k: order.append("writes") or [],
    )
    monkeypatch.setattr(
        main_module.ehal_live, "write_flexible_consumer_states", lambda *a, **k: []
    )

    def failing_basis(*_a, **_k):
        order.append("basis")
        raise RuntimeError("basis update failed")

    monkeypatch.setattr(powerstation_live, "update_reserve_fill_basis", failing_basis)
    with pytest.raises(RuntimeError, match="basis update failed"):
        main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)
    assert order == ["writes", "basis"]


# --- finding 5: read errors in the wait-loop check ---------------------------------------------


def test_wait_loop_logs_a_failed_config_read_once_per_wait(monkeypatch, caplog) -> None:
    def broken():
        raise OSError("config unreadable")

    monkeypatch.setattr(powerstation_live.config, "get_resolved_runtime_settings", broken)
    monkeypatch.setattr(powerstation_live, "_reserve_appliances", lambda *_a: [])
    errors = powerstation_live.WaitReadErrors()
    with caplog.at_level(logging.WARNING, logger=powerstation_live.__name__):
        for _ in range(3):
            assert powerstation_live.release_virtual_reserves_on_appliance_start(errors) == []
    hits = [r for r in caplog.records if "config unreadable" in r.getMessage()]
    assert len(hits) == 1
    # the next wait logs it again
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=powerstation_live.__name__):
        powerstation_live.release_virtual_reserves_on_appliance_start(
            powerstation_live.WaitReadErrors()
        )
    assert "config unreadable" in caplog.text


def test_failed_live_power_read_is_reported_not_swallowed(monkeypatch) -> None:
    import integrations.ehal_live as ehal_live

    def broken(_consumer):
        raise ConnectionError("hub offline")

    monkeypatch.setattr(ehal_live, "resolve_consumer_live_power_kw", broken)
    seen: list[tuple[str, str]] = []
    active = powerstation_live.appliance_run_signal_active(
        "wm",
        telemetry=None,
        consumers_by_id={"wm": {"id": "wm"}},
        on_read_error=lambda source, exc: seen.append((source, str(exc))),
    )
    assert active is False
    assert seen == [("Leistung von wm", "hub offline")]
