"""Planning and chart slots step in real time across DST changes (fixed-offset slot keys)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import config
from data import market_prices as mp
from data.planning_window import hourly_slots_inclusive
from runtime_store.history_timeline import quarter_hour_slots_between
from runtime_store.savings_ledger import _grid_slot_starts

VIENNA = ZoneInfo("Europe/Vienna")
QH = timedelta(minutes=15)


@pytest.fixture(autouse=True)
def vienna(monkeypatch):
    monkeypatch.setattr(config, "get_planning_timezone", lambda: "Europe/Vienna")


def _assert_real_time_grid(slots) -> None:
    instants = [slot.astimezone(UTC) for slot in slots]
    assert len(set(instants)) == len(slots)
    assert all(b - a == QH for a, b in zip(instants, instants[1:]))
    for slot in slots:
        local = slot.astimezone(VIENNA)
        assert (slot.hour, slot.minute) == (local.hour, local.minute)


def test_autumn_night_keeps_the_repeated_hour():
    slots = hourly_slots_inclusive(
        datetime(2026, 10, 24, 22, 0, tzinfo=VIENNA), datetime(2026, 10, 25, 4, 0, tzinfo=VIENNA)
    )

    assert len(slots) == 7 * 4 + 1
    _assert_real_time_grid(slots)
    two_oclock = [slot for slot in slots if (slot.hour, slot.minute) == (2, 0)]
    assert [slot.utcoffset() for slot in two_oclock] == [timedelta(hours=2), timedelta(hours=1)]
    assert len(set(two_oclock)) == 2


def test_spring_night_skips_the_missing_hour():
    slots = hourly_slots_inclusive(
        datetime(2026, 3, 28, 22, 0, tzinfo=VIENNA), datetime(2026, 3, 29, 4, 0, tzinfo=VIENNA)
    )

    assert len(slots) == 5 * 4 + 1
    _assert_real_time_grid(slots)
    assert not [slot for slot in slots if slot.hour == 2]


@pytest.mark.parametrize(("day", "expected"), [(datetime(2026, 3, 29), 92), (datetime(2026, 10, 25), 100)])
def test_chart_axis_of_a_dst_day(day, expected):
    start = day.replace(tzinfo=VIENNA)
    end = (day + timedelta(days=1)).replace(tzinfo=VIENNA)

    slots = quarter_hour_slots_between(start, end)

    assert len(slots) == expected
    _assert_real_time_grid(slots)


@pytest.mark.parametrize(("day", "expected"), [(datetime(2026, 3, 29), 92), (datetime(2026, 10, 25), 100)])
def test_ledger_grid_of_a_dst_day(day, expected):
    start = day.replace(tzinfo=VIENNA)
    end = (day + timedelta(days=1)).replace(tzinfo=VIENNA)

    assert len(_grid_slot_starts(start, end, 0.25)) == expected


def test_ledger_grid_matches_slots_booked_as_iso_strings():
    start = datetime(2026, 10, 25, tzinfo=VIENNA)
    end = datetime(2026, 10, 26, tzinfo=VIENNA)
    grid = _grid_slot_starts(start, end, 0.25)
    booked = {datetime.fromisoformat(slot.isoformat()) for slot in grid}

    assert all(slot in booked for slot in grid)


def test_price_slots_of_the_repeated_hour_are_distinct():
    first = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # 02:30 +02:00
    second = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)  # 02:30 +01:00

    a, b = mp.normalize_price_slot(first), mp.normalize_price_slot(second)

    assert (a.hour, a.minute) == (b.hour, b.minute) == (2, 30)
    assert a != b


def test_market_index_does_not_merge_the_repeated_hour():
    data = [
        {"timestamp": datetime(2026, 10, 25, 0, 0, tzinfo=UTC), "price_buy": 10.0},
        {"timestamp": datetime(2026, 10, 25, 1, 0, tzinfo=UTC), "price_buy": 30.0},
    ]

    indexed = mp.index_market_data_by_slot(data)

    assert sorted(row["price_buy"] for row in indexed.values()) == [10.0, 30.0]


def test_naive_price_slot_is_local_wall_clock():
    slot = mp.normalize_price_slot(datetime(2026, 6, 1, 12, 20))

    assert (slot.hour, slot.minute, slot.utcoffset()) == (12, 15, timedelta(hours=2))
