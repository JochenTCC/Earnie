"""Savings ledger v4: the shadow plant runs the plan battery's limits of each slot's cycle.

Live charge/discharge limits and the virtual reserve floor bind the shadow battery as they bind
the cycle's baselines (``docs/dev/savings-ledger.md`` § 3, § 9 item 16).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import main as main_module
from optimizer.milp import HORIZON_SCHEDULE_KEY
from optimizer.run_trigger import TRIGGER_QUARTER_HOUR
from optimizer.sim_baseline import plan_battery_limits
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from tests.main_run_harness import patch_main_run

FLOOR = "_virtual_reserve_floor_soc"
BATTERY = {
    "battery_capacity_kwh": 10.0,
    "efficiency": 0.9,
    "min_soc": 10.0,
    "max_soc": 90.0,
    "max_power_kw": 2.0,
    "standby_power_kw": 0.0,
}
BUY = 30.0
SELL = 8.0
DT = 0.25
SLOT = datetime(2026, 11, 24, 12, 0, tzinfo=ZoneInfo("Europe/Vienna"))


def _closed(pv: float, house: float, grid: float) -> dict:
    return {
        "interval_start": "2026-11-24T12:00:00",
        "sample_count": 30,
        "pv_kw": pv,
        "grid_kw": grid,
        "battery_kw": 0.0,
        "house_kw": house,
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
    }


def _step(closed, soc, limits):
    return sl.advance_slot(
        closed, soc, BATTERY, k_act_cent=BUY, k_push_cent=SELL, dt_h=DT, shadow_limits=limits
    )


def test_live_discharge_limit_zero_binds_the_shadow_battery():
    deficit = _closed(pv=0.0, house=1.0, grid=1.0)
    free = _step(deficit, 50.0, None)
    locked = _step(deficit, 50.0, {"max_discharge_power_kw": 0.0})

    assert free.shadow_battery_kw == pytest.approx(-1.0)
    assert locked.shadow_battery_kw == pytest.approx(0.0)
    assert locked.shadow_soc_next == pytest.approx(50.0)
    assert locked.cost_without_eur == pytest.approx(1.0 * DT * BUY / 100)


def test_live_charge_limit_binds_the_shadow_battery():
    surplus = _closed(pv=3.0, house=1.0, grid=-2.0)
    slot = _step(surplus, 50.0, {"max_charge_power_kw": 0.5})

    assert slot.shadow_battery_kw == pytest.approx(0.5)
    assert slot.export_kwh_without == pytest.approx(1.5 * DT)


def test_virtual_reserve_floor_is_the_shadow_minimum():
    slot = _step(_closed(pv=0.0, house=2.0, grid=2.0), 30.5, {FLOOR: 30.0})

    assert slot.shadow_soc_next == pytest.approx(30.0)


def test_day_replay_steps_each_slot_under_its_own_limits():
    """The day close replays the rows; with the logged timing it equals the causal slots."""
    closed = [_closed(0.0, 1.0, 1.0), _closed(0.0, 1.0, 1.0), _closed(3.0, 1.0, -2.0)]
    limits = [{"max_discharge_power_kw": 0.0}, None, {"max_charge_power_kw": 0.5, FLOOR: 20.0}]
    soc = 50.0
    rows = []
    for index, (c, lim) in enumerate(zip(closed, limits)):
        inp = sl.LedgerInput(
            SLOT.replace(minute=15 * index), c, BUY, SELL, shadow_limits=lim
        )
        slot = _step(c, soc, lim)
        rows.append(sl._slot_row(inp, slot, DT))
        soc = slot.shadow_soc_next
    assert rows[0]["shadow_limits"] == {"max_discharge_power_kw": 0.0}
    assert "shadow_limits" not in rows[1]

    replayed, end_soc = sl.replay_day(rows, 50.0, BATTERY, None, dt_h=DT)

    assert end_soc == pytest.approx(soc)
    for causal, again in zip(rows, replayed):
        assert again["cost_without_eur"] == pytest.approx(causal["cost_without_eur"])
        assert again["shadow_soc_end"] == pytest.approx(causal["shadow_soc_end"])


def test_log_entry_limits_reach_the_ledger_input():
    entry = {
        "k_push_act": SELL,
        "market_price_cent": BUY,
        "shadow_battery_limits": {"max_discharge_power_kw": 0, FLOOR: 21.5},
    }
    pending = store.pending_slot_from_entry(SLOT, entry)
    inp = store.ledger_input_from_pending(SLOT, _closed(0.0, 1.0, 1.0), pending, batteries=[])

    assert inp.shadow_limits == {"max_discharge_power_kw": 0.0, FLOOR: 21.5}


def test_log_entry_from_before_v4_has_no_limits():
    pending = store.pending_slot_from_entry(SLOT, {"k_push_act": SELL, "market_price_cent": BUY})
    inp = store.ledger_input_from_pending(SLOT, _closed(0.0, 1.0, 1.0), pending, batteries=[])

    assert inp.shadow_limits is None


def test_malformed_limits_fail_loud():
    with pytest.raises(ValueError, match="shadow_battery_limits"):
        store.pending_slot_from_entry(
            SLOT, {"k_push_act": SELL, "market_price_cent": BUY, "shadow_battery_limits": [0.0]}
        )


def test_plan_battery_limits_of_several_batteries_are_the_plant_battery():
    first = {**BATTERY, "id": "a", "max_charge_power_kw": 2.0, "max_discharge_power_kw": 0.0, FLOOR: 25.0}
    second = {**BATTERY, "id": "b", "max_charge_power_kw": 1.0, "max_discharge_power_kw": 1.5}

    assert plan_battery_limits(first) == {
        "max_charge_power_kw": 2.0,
        "max_discharge_power_kw": 0.0,
        FLOOR: 25.0,
    }
    plant = plan_battery_limits([first, second])
    assert plant["max_charge_power_kw"] == pytest.approx(3.0)
    assert plant["max_discharge_power_kw"] == pytest.approx(1.5)


def test_main_logs_the_plan_battery_limits_for_the_ledger(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
    monkeypatch.setattr(main_module.optimizer, "calculate_optimization_savings", lambda *a, **k: None)
    sent: list = []

    def _milp(*_a, **k):
        sent.append(k["battery_params"])
        return (0, 0.0, 99.0, {}, {}, {HORIZON_SCHEDULE_KEY: [{}]}, {})

    monkeypatch.setattr(main_module.optimizer, "milp_optimizer", _milp)
    payloads: list[dict] = []
    monkeypatch.setattr(main_module.run_state, "save_run_state", payloads.append)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert len(payloads) == 1 and len(sent) == 1
    assert payloads[0]["shadow_battery_limits"] == plan_battery_limits(sent[0])
