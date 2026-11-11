"""Ledger P5: daemon hook (spec savings-ledger.md § 4 "Where it runs")."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_daemon as hook
from runtime_store import savings_ledger_store as store

TZ = ZoneInfo("Europe/Vienna")
BATTERY = {
    "battery_capacity_kwh": 10.0,
    "efficiency": 1.0,
    "min_soc": 10.0,
    "max_soc": 90.0,
    "max_power_kw": 2.0,
    "standby_power_kw": 0.0,
}


def _day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    start = moment.replace(hour=7, minute=0, second=0, microsecond=0)
    if moment < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    state_path = tmp_path / "savings_ledger_state.json"
    rows_path = tmp_path / "savings_ledger.jsonl"
    monkeypatch.setattr(store, "savings_ledger_state_file", lambda: str(state_path))
    monkeypatch.setattr(store, "savings_ledger_file", lambda: str(rows_path))
    monkeypatch.setattr(store, "savings_ledger_slots_file", lambda: str(tmp_path / "savings_ledger_slots.jsonl"))
    monkeypatch.setattr(store, "sunrise_day_bounds", lambda *_a: _day_bounds)
    monkeypatch.setattr("config.get_planning_timezone", lambda: "Europe/Vienna")
    monkeypatch.setattr("config.get_battery_params_list", lambda: [dict(BATTERY)])
    hook.reset()
    yield state_path, rows_path
    hook.reset()


def _close_one_day() -> dict:
    _cycle("2026-11-02T06:45:03", _closed("2026-11-02T06:30:00"))
    _cycle("2026-11-02T07:00:02", _closed("2026-11-02T06:45:00"))
    return _cycle("2026-11-02T07:15:04", _closed("2026-11-02T07:00:00"))


def test_day_close_writes_the_slots_of_the_closed_day(ledger):
    row = _close_one_day()

    slots = store.closed_day_slots([row])[row["day_start"]]

    assert [s["counted"] for s in slots] == [False, True]
    assert slots[1]["house_kwh"] == pytest.approx(0.25)
    assert slots[1]["cost_with_eur"] == pytest.approx(row["cost_with_eur"])


def test_failed_slot_write_keeps_the_row_warns_and_readers_fail_loud(ledger, monkeypatch, caplog):
    _, rows_path = ledger

    def fail(_record):
        raise OSError("disk full")

    monkeypatch.setattr(store, "append_day_slots", fail)
    with caplog.at_level(logging.WARNING):
        row = _close_one_day()

    assert store.read_rows(str(rows_path)) == [row]
    assert "disk full" in caplog.text
    assert "--since 2026-11-02 --slots-only" in caplog.text
    # the chain went on: the next cycle does not close the same day again
    assert _cycle("2026-11-02T07:30:02", _closed("2026-11-02T07:15:00")) is None
    assert len(store.read_rows(str(rows_path))) == 1
    with pytest.raises(store.SlotFileError):
        store.closed_day_slots([row])


def test_open_day_of_an_older_state_closes_without_slots_and_warns(ledger, caplog):
    state_path, rows_path = ledger
    _cycle("2026-11-02T06:45:03", _closed("2026-11-02T06:30:00"))
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    for slot in saved["slots"]:
        del slot["house_kwh"]
    state_path.write_text(json.dumps(saved), encoding="utf-8")
    hook.reset()

    with caplog.at_level(logging.WARNING):
        _cycle("2026-11-02T07:00:02", _closed("2026-11-02T06:45:00"))
        row = _cycle("2026-11-02T07:15:04", _closed("2026-11-02T07:00:00"))

    assert store.read_rows(str(rows_path)) == [row]
    assert "--slots-only" in caplog.text
    with pytest.raises(store.SlotFileError, match="is missing"):
        store.closed_day_slots([row])


def _closed(start: str, soc0: float = 50.0, soc1: float = 50.0) -> dict:
    return {
        "interval_start": start,
        "sample_count": 30,
        "pv_kw": 0.0,
        "grid_kw": 1.0,
        "battery_kw": 0.0,
        "house_kw": 1.0,
        "soc_start_percent": soc0,
        "soc_end_percent": soc1,
        "flex_kw": {},
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
    }


def _payload(price: float = 30.0) -> dict:
    return {
        "market_price_cent": price,
        "epex_price_cent": 10.0,
        "k_push_act": 8.0,
        "delivery_compliance": {"wp": {"planned_kw": 0.4}},
    }


def _cycle(now: str, closed: dict | None, price: float = 30.0):
    return hook.on_cycle(closed, _payload(price), now=datetime.fromisoformat(now))


def test_cycles_book_slots_and_close_the_day(ledger):
    state_path, rows_path = ledger

    # 06:45: closes 06:30 (no prices stored for it yet), starts the chain
    assert _cycle("2026-11-02T06:45:03", _closed("2026-11-02T06:30:00")) is None
    # 07:00: closes 06:45 with the prices stored at 06:45
    assert _cycle("2026-11-02T07:00:02", _closed("2026-11-02T06:45:00")) is None
    # 07:15: closes 07:00, the first slot of the next SA-day → row for the day ending 07:00
    row = _cycle("2026-11-02T07:15:04", _closed("2026-11-02T07:00:00"))

    assert row is not None
    assert row["day_end"] == datetime(2026, 11, 2, 7, 0, tzinfo=TZ).isoformat()
    assert row["slots_present"] == 1
    # 94 quarter hours of the day lie before the chain start at 06:30
    assert row["slots_skipped"] == {sl.SKIP_BEFORE_CHAIN: 94, sl.SKIP_NO_PRICE: 1}
    assert row["slots_present"] + sum(row["slots_skipped"].values()) == row["slots_total"]
    assert row["chain_start_reason"] == sl.CHAIN_FIRST_RUN
    assert row["flex_planned_kwh"] == {"wp": pytest.approx(0.1)}
    assert row["errors"] == 0
    assert store.read_rows(str(rows_path)) == [row]

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["day_start"] == datetime(2026, 11, 2, 7, 0, tzinfo=TZ).isoformat()
    assert saved["pending_slot"]["slot_start"] == datetime(2026, 11, 2, 7, 15, tzinfo=TZ).isoformat()
    assert saved["chain_start"] == datetime(2026, 11, 2, 6, 30, tzinfo=TZ).isoformat()


def test_restart_resumes_from_the_state_file_without_reseeding(ledger):
    state_path, _ = ledger
    _cycle("2026-11-02T10:00:01", _closed("2026-11-02T09:45:00", soc0=50.0))
    _cycle("2026-11-02T10:15:01", _closed("2026-11-02T10:00:00"))
    before = json.loads(state_path.read_text(encoding="utf-8"))

    hook.reset()  # daemon restart
    _cycle("2026-11-02T10:30:01", _closed("2026-11-02T10:15:00", soc0=85.0, soc1=85.0))
    after = json.loads(state_path.read_text(encoding="utf-8"))

    assert after["chain_start"] == before["chain_start"]
    # the shadow kept its own chain (discharging from 50 %), not the live 85 %
    assert after["shadow_soc"] < before["shadow_soc"] < 50.0
    assert [s["counted"] for s in after["slots"]] == [False, True, True]


def test_slot_after_downtime_has_no_price(ledger):
    _cycle("2026-11-02T10:00:01", _closed("2026-11-02T09:45:00"))
    hook.reset()
    # the 10:00 cycle never ran: its slot has no stored prices
    _cycle("2026-11-02T11:00:01", _closed("2026-11-02T10:45:00"))

    state = store.load_state().state
    assert state.slots[-1]["skip_reason"] == sl.SKIP_NO_PRICE


def test_error_logs_a_warning_and_is_counted_in_the_day_row(ledger, monkeypatch, caplog):
    _cycle("2026-11-02T06:15:01", _closed("2026-11-02T06:00:00"))

    def boom(*_args, **_kwargs):
        raise RuntimeError("shadow step failed")

    # the hook books through ``advance_with_slots`` (it also needs the closed day's slot source)
    original = sl.advance_with_slots
    monkeypatch.setattr(sl, "advance_with_slots", boom)
    with caplog.at_level(logging.WARNING):
        assert _cycle("2026-11-02T06:30:01", _closed("2026-11-02T06:15:00")) is None
    assert "cycle not booked" in caplog.text
    monkeypatch.setattr(sl, "advance_with_slots", original)

    row = _cycle("2026-11-02T07:15:01", _closed("2026-11-02T07:00:00"))

    assert row["errors"] == 1
    assert row["slots_skipped"][sl.SKIP_ERROR] == 1


def test_broken_state_starts_a_new_chain_with_its_reason(ledger, caplog):
    state_path, _ = ledger
    state_path.write_text("{broken", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        _cycle("2026-11-02T06:45:01", _closed("2026-11-02T06:30:00"))
    row = _cycle("2026-11-02T07:15:01", _closed("2026-11-02T07:00:00"))

    assert "unreadable" in caplog.text
    assert row["chain_start_reason"] == sl.CHAIN_STATE_UNREADABLE
    assert list(state_path.parent.glob("savings_ledger_state.json.broken-*"))


def test_without_house_battery_the_ledger_runs_without_shadow_battery(ledger, monkeypatch, caplog):
    """D3 (savings_v 2): no house battery → shadow plant without battery, no SoC correction."""
    state_path, rows_path = ledger
    monkeypatch.setattr("config.get_battery_params_list", lambda: [])

    with caplog.at_level(logging.INFO):
        assert _cycle("2026-11-02T06:45:01", _closed("2026-11-02T06:30:00")) is None
        assert _cycle("2026-11-02T07:00:01", _closed("2026-11-02T06:45:00")) is None
        row = _cycle("2026-11-02T07:15:01", _closed("2026-11-02T07:00:00"))

    assert "no house battery" in caplog.text
    state = store.load_state().state
    assert state.shadow_soc is None and state.shadow_soc_day_start is None
    assert row["p_ref_basis"] == sl.P_REF_NO_BATTERY
    assert row["soc_correction_eur"] == 0.0
    # grid = load − pv on both sides: no battery, no saving
    assert row["saving_eur"] == 0.0
    assert rows_path.exists()


def test_out_of_band_cycle_only_updates_the_prices(ledger):
    _cycle("2026-11-02T10:00:01", _closed("2026-11-02T09:45:00"), price=30.0)
    # out-of-band run in the same slot: no closed interval, newer prices win
    _cycle("2026-11-02T10:07:30", None, price=45.0)
    _cycle("2026-11-02T10:15:01", _closed("2026-11-02T10:00:00"))

    state = store.load_state().state
    assert state.slots[-1]["k_act_cent"] == 45.0
