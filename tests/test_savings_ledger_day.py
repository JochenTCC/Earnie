"""Ledger P4: SA-day close, SoC correction, state and ledger files (spec savings-ledger.md § 3, § 4)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ledger_flex_helpers import no_flex
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store

TZ = ZoneInfo("Europe/Vienna")
DAY1 = datetime(2026, 11, 1, 7, 0, tzinfo=TZ)
BATTERY = {
    "battery_capacity_kwh": 10.0,
    "efficiency": 1.0,
    "min_soc": 10.0,
    "max_soc": 90.0,
    "max_power_kw": 2.0,
    "standby_power_kw": 0.0,
}


def day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """Fixed 07:00 → 07:00 days for the tests."""
    start = moment.replace(hour=7, minute=0, second=0, microsecond=0)
    if moment < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def _closed(pv=0.0, house=1.0, grid=1.0, battery=0.0, soc0=50.0, soc1=50.0) -> dict:
    return {
        "sample_count": 30,
        "pv_kw": pv,
        "grid_kw": grid,
        "battery_kw": battery,
        "house_kw": house,
        "soc_start_percent": soc0,
        "soc_end_percent": soc1,
        "flex_kw": {"wp": 0.4},
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
    }


def _inp(slot_start, closed, price=30.0, push=8.0) -> sl.LedgerInput:
    return sl.LedgerInput(slot_start, closed, price, push, {"wp": 0.5})


def _run(inputs, state=None):
    rows = []
    if state is None:
        state = sl.start_chain(inputs[0], day_bounds, reason=sl.CHAIN_FIRST_RUN)
    for inp in inputs:
        state, row = sl.advance(state, inp, BATTERY, day_bounds, app_version="test", day_flex=no_flex)
        if row is not None:
            rows.append(row)
    return state, rows


def _slots(day_start, n=96):
    return [day_start + timedelta(minutes=15 * i) for i in range(n)]


def _two_day_log():
    """Day 1: Earnie holds the battery at 50 %; day 2: it discharges to 10 %.

    The shadow discharges on day 1 (to min_soc after 16 slots) and has nothing
    left on day 2. Prices are flat 30 ct, so holding energy for a day is worth nothing.
    """
    day1 = [_inp(s, _closed()) for s in _slots(DAY1)]
    day2 = []
    soc = 50.0
    for i, s in enumerate(_slots(DAY1 + timedelta(days=1))):
        if i < 16:
            day2.append(_inp(s, _closed(grid=0.0, battery=1.0, soc0=soc, soc1=soc - 2.5)))
            soc -= 2.5
        else:
            day2.append(_inp(s, _closed(soc0=10.0, soc1=10.0)))
    closer = [_inp(DAY1 + timedelta(days=2), _closed(soc0=10.0, soc1=10.0))]
    return day1 + day2 + closer


def test_day_rows_and_correction_reversed_next_day():
    state, rows = _run(_two_day_log())

    assert len(rows) == 2
    day1, day2 = rows
    assert day1["slots_total"] == 96 and day1["slots_present"] == 96
    assert day1["cost_with_eur"] == pytest.approx(96 * 0.25 * 0.30)
    assert day1["cost_without_eur"] == pytest.approx(80 * 0.25 * 0.30)
    assert day1["soc_actual_end_pct"] == 50.0
    assert day1["soc_shadow_end_pct"] == pytest.approx(10.0)
    assert day1["p_ref_basis"] == sl.P_REF_IMPORT_WEIGHTED
    assert day1["p_ref_cent"] == pytest.approx(30.0)
    # 40 % of 10 kWh at 30 ct
    assert day1["soc_correction_eur"] == pytest.approx(1.2)
    assert day1["soc_correction_prev_eur"] == 0.0
    assert day1["saving_adjusted_eur"] == pytest.approx(0.0)
    assert day1["chain_start_reason"] == sl.CHAIN_FIRST_RUN
    assert day1["flex_planned_kwh"] == {"wp": pytest.approx(12.0)}
    assert day1["flex_delivered_kwh"] == {"wp": pytest.approx(9.6)}

    assert day2["saving_eur"] == pytest.approx(16 * 0.25 * 0.30)
    assert day2["soc_correction_eur"] == pytest.approx(0.0)
    assert day2["soc_correction_prev_eur"] == pytest.approx(1.2)
    assert day2["saving_adjusted_eur"] == pytest.approx(0.0)
    assert "chain_start_reason" not in day2

    total = sl.lifetime_summary(rows, state.chain_start)
    # telescoping: Σ adjusted = Σ saving + correction of the last day
    assert total["saving_adjusted_eur"] == pytest.approx(
        day1["saving_eur"] + day2["saving_eur"] + day2["soc_correction_eur"]
    )
    assert total["days"] == 2


def test_lifetime_total_does_not_depend_on_the_evening_soc():
    """Day 1 shown before and after its correction: the evening reserve only moves euros between days."""
    _, rows = _run(_two_day_log())
    without_correction = rows[0]["saving_eur"] + rows[1]["saving_eur"]
    with_correction = sum(r["saving_adjusted_eur"] for r in rows)
    assert with_correction == pytest.approx(without_correction + rows[1]["soc_correction_eur"])
    assert rows[0]["saving_eur"] < 0 < rows[1]["saving_eur"]


def test_incomplete_day_is_flagged_and_counted():
    inputs = [
        _inp(s, _closed(grid=0.5, house=0.5) if i < 50 else None)
        for i, s in enumerate(_slots(DAY1))
    ]
    inputs.append(_inp(DAY1 + timedelta(days=1), _closed()))
    state, rows = _run(inputs)

    (row,) = rows
    assert row["slots_present"] == 50
    assert row["coverage"] == pytest.approx(50 / 96, abs=1e-3)
    assert row["incomplete"] is True
    assert row["slots_skipped"] == {sl.SKIP_MISSING: 46}
    total = sl.lifetime_summary(rows, state.chain_start)
    assert total["incomplete_days"] == 1
    assert total["saving_adjusted_eur"] == pytest.approx(row["saving_adjusted_eur"])


def test_unbooked_slots_are_skipped_before_chain_or_without_cycle():
    """Live row 2026-11-02: slots before the chain start and quarter hours without a cycle left no trace."""
    slots = _slots(DAY1)
    chain_start = 24  # chain starts at 13:00
    gaps = {34, 38}  # 15:30 and 16:30 without a completed cycle
    inputs = [_inp(s, _closed()) for i, s in enumerate(slots) if i >= chain_start and i not in gaps]
    inputs.append(_inp(DAY1 + timedelta(days=1), _closed()))
    _, rows = _run(inputs)

    (row,) = rows
    assert row["slots_total"] == 96
    assert row["slots_present"] == 70
    assert row["slots_skipped"] == {sl.SKIP_BEFORE_CHAIN: 24, sl.SKIP_NO_CYCLE: 2}
    assert row["slots_present"] + sum(row["slots_skipped"].values()) == row["slots_total"]
    assert row["errors"] == 0


def test_missing_tail_of_the_day_counts_as_no_cycle():
    inputs = [_inp(s, _closed()) for s in _slots(DAY1, 90)]
    inputs.append(_inp(DAY1 + timedelta(days=1), _closed()))
    _, rows = _run(inputs)

    (row,) = rows
    assert row["slots_skipped"] == {sl.SKIP_NO_CYCLE: 6}
    assert row["slots_present"] + sum(row["slots_skipped"].values()) == row["slots_total"]


def test_day_without_import_uses_the_time_mean():
    inputs = []
    for i, s in enumerate(_slots(DAY1)):
        # PV covers the house and exports; actual battery idle at 50 %
        inputs.append(_inp(s, _closed(pv=2.0, house=1.0, grid=-1.0), price=20.0 if i % 2 else 40.0))
    inputs.append(_inp(DAY1 + timedelta(days=1), _closed()))
    _, rows = _run(inputs)

    (row,) = rows
    assert row["import_kwh_with"] == 0.0
    assert row["p_ref_basis"] == sl.P_REF_TIME_MEAN
    assert row["p_ref_cent"] == pytest.approx(30.0)


def test_day_without_counted_slot_carries_the_correction():
    day1 = [_inp(s, _closed()) for s in _slots(DAY1)]
    day2 = [_inp(s, None) for s in _slots(DAY1 + timedelta(days=1))]
    closer = [_inp(DAY1 + timedelta(days=2), _closed())]
    _, rows = _run(day1 + day2 + closer)

    assert rows[1]["slots_present"] == 0
    assert rows[1]["p_ref_basis"] == sl.P_REF_CARRIED
    assert rows[1]["soc_correction_eur"] == pytest.approx(rows[0]["soc_correction_eur"])
    assert rows[1]["saving_adjusted_eur"] == pytest.approx(0.0)


def test_slot_without_price_is_skipped():
    state = sl.start_chain(_inp(DAY1, _closed()), day_bounds, reason=sl.CHAIN_FIRST_RUN)
    state, _ = sl.advance(
        state, sl.LedgerInput(DAY1, _closed(), None, None), BATTERY, day_bounds, app_version="t"
    )
    assert state.slots[0]["counted"] is False
    assert state.slots[0]["skip_reason"] == sl.SKIP_NO_PRICE
    assert state.shadow_soc == 50.0


def test_replayed_slot_is_ignored():
    inputs = [_inp(s, _closed()) for s in _slots(DAY1, 4)]
    state, _ = _run(inputs)
    again, row = sl.advance(state, inputs[2], BATTERY, day_bounds, app_version="t", day_flex=no_flex)
    assert again is state and row is None


def test_state_round_trip_resumes_the_chain(tmp_path):
    log = _two_day_log()
    reference_state, reference_rows = _run(log)

    state, rows = _run(log[:100])
    path = tmp_path / "state.json"
    store.save_state(state, str(path))
    loaded = store.load_state(str(path))
    assert loaded.restart_reason is None
    resumed, more = _run(log[100:], state=loaded.state)

    assert rows + more == reference_rows
    assert resumed.to_dict() == reference_state.to_dict()


def test_missing_state_starts_a_first_chain(tmp_path):
    loaded = store.load_state(str(tmp_path / "none.json"))
    assert loaded.state is None and loaded.restart_reason == sl.CHAIN_FIRST_RUN


def test_savings_v_change_starts_a_new_chain(tmp_path):
    state, _ = _run([_inp(DAY1, _closed())])
    raw = state.to_dict()
    raw["savings_v"] = sl.SAVINGS_V + 1
    path = tmp_path / "state.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = store.load_state(str(path))
    assert loaded.state is None and loaded.restart_reason == sl.CHAIN_SAVINGS_V_CHANGED

    new = sl.start_chain(_inp(DAY1 + timedelta(days=3), _closed()), day_bounds, reason=loaded.restart_reason)
    _, rows = _run(
        [_inp(DAY1 + timedelta(days=3), _closed()), _inp(DAY1 + timedelta(days=4), _closed())],
        state=new,
    )
    assert rows[0]["chain_start_reason"] == sl.CHAIN_SAVINGS_V_CHANGED
    assert rows[0]["chain_start"] == (DAY1 + timedelta(days=3)).isoformat()


def test_broken_state_is_moved_aside_with_a_warning(tmp_path, caplog):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")

    loaded = store.load_state(str(path), now=datetime(2026, 11, 2, 8, 0))

    assert loaded.state is None and loaded.restart_reason == sl.CHAIN_STATE_UNREADABLE
    assert not path.exists()
    assert (tmp_path / "state.json.broken-20261102-080000").read_text(encoding="utf-8") == "{not json"
    assert "unreadable" in caplog.text


def test_state_missing_a_field_counts_as_broken(tmp_path):
    state, _ = _run([_inp(DAY1, _closed())])
    raw = state.to_dict()
    del raw["shadow_soc"]
    path = tmp_path / "state.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert store.load_state(str(path)).restart_reason == sl.CHAIN_STATE_UNREADABLE


def test_ledger_file_append_and_read(tmp_path):
    _, rows = _run(_two_day_log())
    path = str(tmp_path / "ledger.jsonl")
    for row in rows:
        store.append_row(row, path)

    assert store.read_rows(path) == rows
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("garbage\n")
    with pytest.raises(ValueError, match="line 3"):
        store.read_rows(path)


def test_log_entries_pair_prices_of_the_slot_with_its_closed_interval(monkeypatch):
    monkeypatch.setattr("config.get_planning_timezone", lambda: "Europe/Vienna")
    closed = {**_closed(), "interval_start": "2026-11-01T12:00:00"}
    entries = [
        {
            "written_at": "2026-11-01T12:00:05",
            "market_price_cent": 31.5,
            "epex_price_cent": 10.0,
            "k_push_act": 7.5,
            "delivery_compliance": {"wp": {"planned_kw": 0.8}},
        },
        {
            "written_at": "2026-11-01T12:15:04",
            "market_price_cent": 99.0,
            "epex_price_cent": 50.0,
            "k_push_act": 1.0,
            "closed_interval": closed,
        },
    ]

    (inp,) = store.ledger_inputs_from_entries(entries, "Europe/Vienna")

    assert inp.slot_start == datetime(2026, 11, 1, 12, 0, tzinfo=TZ)
    assert inp.closed is closed
    assert inp.k_act_cent == 31.5
    assert inp.k_push_cent == 7.5
    assert inp.planned_flex_kw == {"wp": 0.8}


def test_slot_without_own_entry_has_no_price(monkeypatch):
    monkeypatch.setattr("config.get_planning_timezone", lambda: "Europe/Vienna")
    closed = {**_closed(), "interval_start": "2026-11-01T12:00:00"}
    entries = [{"written_at": "2026-11-01T12:15:04", "market_price_cent": 30.0, "k_push_act": 8.0, "closed_interval": closed}]

    (inp,) = store.ledger_inputs_from_entries(entries, "Europe/Vienna")

    assert inp.k_act_cent is None and inp.k_push_cent is None


def test_sunrise_day_bounds_contain_the_moment():
    bounds = store.sunrise_day_bounds(48.2, 16.37, "Europe/Vienna")
    noon = datetime(2026, 11, 1, 12, 0, tzinfo=TZ)
    start, end = bounds(noon)
    assert start <= noon < end
    assert start.date() == noon.date() and end.date() == noon.date() + timedelta(days=1)
    early = datetime(2026, 11, 2, 5, 0, tzinfo=TZ)
    assert bounds(early) == (start, end)
