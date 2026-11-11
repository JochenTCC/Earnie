"""Account view P1: slot series of closed SA-days (spec chart2-account-view.md § 4)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ledger_flex_helpers import no_flex
from runtime_store import savings_ledger as sl
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


def _closed(grid_kw: float, house_kw: float, sample_count: int = 30) -> dict:
    return {
        "sample_count": sample_count,
        "pv_kw": 0.3,
        "grid_kw": grid_kw,
        "battery_kw": house_kw - grid_kw - 0.3,
        "house_kw": house_kw,
        "soc_start_percent": 50.0,
        "soc_end_percent": 50.0,
        "flex_kw": {},
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
    }


def _closed_day() -> tuple[dict, dict]:
    """A day of counted slots with changing prices, one slot with too few samples, one without a price."""
    start = datetime(2026, 11, 1, 7, 0, tzinfo=TZ)
    inputs = [
        sl.LedgerInput(start + timedelta(minutes=15 * i), _closed(1.0 + 0.1 * i, 1.5), 30.0 + i, 8.0)
        for i in range(6)
    ]
    inputs.append(sl.LedgerInput(start + timedelta(minutes=90), _closed(1.0, 1.5, sample_count=1), 30.0, 8.0))
    inputs.append(sl.LedgerInput(start + timedelta(minutes=105), _closed(1.0, 1.5), None, None))
    state = sl.start_chain(inputs[0], _day_bounds, reason=sl.CHAIN_FIRST_RUN)
    for inp in inputs:
        state, _ = sl.advance(state, inp, BATTERY, _day_bounds, app_version="test", day_flex=no_flex)
    closing = state
    next_slot = sl.LedgerInput(start + timedelta(days=1), _closed(1.0, 1.5), 30.0, 8.0)
    _, row = sl.advance(state, next_slot, BATTERY, _day_bounds, app_version="test", day_flex=no_flex)
    return row, sl.day_slots_record(closing)


def test_slot_sum_of_a_closed_day_equals_its_ledger_row():
    row, record = _closed_day()

    assert len(record["slots"]) == 8
    assert record["day_start"] == row["day_start"]
    assert round(sum(s["cost_with_eur"] for s in record["slots"]), 4) == row["cost_with_eur"]
    assert round(sum(s["cost_without_eur"] for s in record["slots"]), 4) == row["cost_without_eur"]
    assert sum(1 for s in record["slots"] if s["counted"]) == row["slots_present"]
    sl.check_day_slots(row, record)


def test_slots_carry_house_energy_and_skipped_slots_count_as_zero():
    _, record = _closed_day()

    counted, skipped = record["slots"][0], record["slots"][6]
    assert counted["counted"] is True
    assert counted["house_kwh"] == pytest.approx(1.5 * 0.25)
    assert skipped["counted"] is False
    assert skipped["skip_reason"] == sl.SKIP_FEW_SAMPLES
    assert (skipped["cost_with_eur"], skipped["cost_without_eur"], skipped["house_kwh"]) == (0.0, 0.0, 0.0)
    assert record["slots"][7]["skip_reason"] == sl.SKIP_NO_PRICE


def test_error_slot_has_all_slot_file_fields():
    start = datetime(2026, 11, 1, 7, 0, tzinfo=TZ)
    state = sl.start_chain(sl.LedgerInput(start, _closed(1.0, 1.5), 30.0, 8.0), _day_bounds, reason="first_run")

    state = sl.record_error_slot(state, start + timedelta(minutes=15))

    assert sl.day_slots_record(state)["slots"][0]["house_kwh"] == 0.0


def test_slot_rows_of_an_older_state_without_house_energy_raise():
    start = datetime(2026, 11, 1, 7, 0, tzinfo=TZ)
    state = sl.start_chain(sl.LedgerInput(start, _closed(1.0, 1.5), 30.0, 8.0), _day_bounds, reason="first_run")
    state, _ = sl.advance(state, sl.LedgerInput(start, _closed(1.0, 1.5), 30.0, 8.0), BATTERY, _day_bounds, app_version="t", day_flex=no_flex)
    old = {k: v for k, v in state.slots[0].items() if k != "house_kwh"}

    with pytest.raises(KeyError, match="house_kwh"):
        sl.day_slots_record(replace(state, slots=(old,)))


def test_round_trip_through_the_slot_file(tmp_path):
    row, record = _closed_day()
    path = str(tmp_path / "slots.jsonl")

    store.append_day_slots(record, path)

    assert store.closed_day_slots([row], path) == {row["day_start"]: record["slots"]}


def test_without_closed_days_no_file_is_expected(tmp_path):
    assert store.closed_day_slots([], str(tmp_path / "missing.jsonl")) == {}


def test_missing_file_fails_loud(tmp_path):
    row, _ = _closed_day()

    with pytest.raises(store.SlotFileError, match="is missing.*--slots-only"):
        store.closed_day_slots([row], str(tmp_path / "missing.jsonl"))


def test_broken_line_fails_loud_with_its_number(tmp_path):
    row, record = _closed_day()
    path = tmp_path / "slots.jsonl"
    store.append_day_slots(record, str(path))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"day_start": "torn\n')

    with pytest.raises(store.SlotFileError, match="line 2"):
        store.closed_day_slots([row], str(path))


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda slot: slot.pop("house_kwh"), "not a number"),
        (lambda slot: slot.update(cost_with_eur="1.0"), "not a number"),
        (lambda slot: slot.update(counted="yes"), "counted"),
        (lambda slot: slot.update(counted=False), "must be zero"),
    ],
)
def test_malformed_slot_fails_loud(tmp_path, change, message):
    row, record = _closed_day()
    change(record["slots"][0])
    path = str(tmp_path / "slots.jsonl")
    store.append_day_slots(record, path)

    with pytest.raises(store.SlotFileError, match=message):
        store.closed_day_slots([row], path)


def test_repeated_day_fails_loud(tmp_path):
    row, record = _closed_day()
    path = str(tmp_path / "slots.jsonl")
    store.append_day_slots(record, path)
    store.append_day_slots(record, path)

    with pytest.raises(store.SlotFileError, match="repeats day"):
        store.closed_day_slots([row], path)


def test_day_without_slots_fails_loud(tmp_path):
    row, record = _closed_day()
    path = str(tmp_path / "slots.jsonl")
    store.append_day_slots(record, path)
    later = dict(row, day_start="2026-11-02T07:00:00+01:00")

    with pytest.raises(store.SlotFileError, match="no slots for day 2026-11-02"):
        store.closed_day_slots([row, later], path)


@pytest.mark.parametrize(
    "key, value",
    [("cost_with_eur", 99.0), ("cost_without_eur", 99.0), ("slots_present", 1)],
)
def test_slots_that_do_not_add_up_to_the_row_fail_loud(tmp_path, key, value):
    row, record = _closed_day()
    path = str(tmp_path / "slots.jsonl")
    store.append_day_slots(record, path)

    with pytest.raises(store.SlotFileError):
        store.closed_day_slots([dict(row, **{key: value})], path)


def test_slot_file_is_one_json_object_per_day(tmp_path):
    _, record = _closed_day()
    path = tmp_path / "slots.jsonl"

    store.append_day_slots(record, str(path))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [record]
