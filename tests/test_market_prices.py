"""Tests für Day-Ahead-Auflösung und Spiegel-Extrapolation."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from zoneinfo import ZoneInfo

from data.market_prices import (
    PRICE_SOURCE_DAY_AHEAD,
    PRICE_SOURCE_MIRRORED,
    hourly_settlement_epex_values,
    index_market_data_by_slot,
    normalize_price_slot,
    resolve_24h_market_slots,
    resolve_market_slots,
)

VIENNA = ZoneInfo("Europe/Vienna")


def _slot(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=VIENNA)


def _market_entry(slot: datetime, price: float) -> dict:
    return {
        "timestamp": slot,
        "hour": slot.hour,
        "price_buy": price,
    }


def test_resolve_24h_uses_day_ahead_when_complete():
    start = datetime(2026, 6, 24, 8, 0, 0)
    target_hours = [start + timedelta(hours=i) for i in range(24)]
    market_data = [
        _market_entry(start + timedelta(hours=i), 10.0 + i)
        for i in range(24)
    ]

    resolved = resolve_24h_market_slots(market_data, target_hours)

    assert len(resolved) == 24
    assert all(slot["price_source"] == PRICE_SOURCE_DAY_AHEAD for slot in resolved)
    assert resolved[0]["price_buy"] == 10.0
    assert resolved[-1]["price_buy"] == 33.0


def test_resolve_24h_mirrors_missing_slots_from_previous_day():
    now = datetime(2026, 6, 24, 10, 0, 0)
    target_hours = [now + timedelta(hours=i) for i in range(24)]
    market_data = [
        _market_entry(datetime(2026, 6, 24, hour, 0), float(hour))
        for hour in range(24)
    ]

    resolved = resolve_24h_market_slots(market_data, target_hours)

    assert len(resolved) == 24
    assert resolved[0]["price_source"] == PRICE_SOURCE_DAY_AHEAD
    assert resolved[0]["price_buy"] == 10.0
    assert resolved[-1]["price_source"] == PRICE_SOURCE_MIRRORED
    assert resolved[-1]["mirrored_from"] == _slot(2026, 6, 24, 9)
    assert resolved[-1]["price_buy"] == 9.0


def test_resolve_24h_raises_when_mirror_source_missing():
    start = datetime(2026, 6, 24, 10, 0, 0)
    target_hours = [start + timedelta(hours=i) for i in range(24)]
    market_data = [_market_entry(start, 12.0)]

    with pytest.raises(ValueError, match="Spiegelquelle"):
        resolve_24h_market_slots(market_data, target_hours)


def test_resolve_24h_accepts_variable_horizon_length():
    start = datetime(2026, 6, 24, 8, 0, 0)
    target_hours = [start + timedelta(hours=i) for i in range(37)]
    market_data = [
        _market_entry(start + timedelta(hours=i), 10.0 + i)
        for i in range(37)
    ]

    resolved = resolve_24h_market_slots(market_data, target_hours)

    assert len(resolved) == 37


def test_resolve_market_slots_mirrors_from_earlier_day_when_previous_day_missing():
    start = datetime(2026, 6, 24, 8, 0, 0)
    target_hours = [datetime(2026, 6, 26, 20, 0, 0)]
    market_data = [_market_entry(datetime(2026, 6, 24, 20, 0, 0), 15.5)]

    resolved = resolve_market_slots(market_data, target_hours)

    assert len(resolved) == 1
    assert resolved[0]["price_source"] == PRICE_SOURCE_MIRRORED
    assert resolved[0]["mirrored_from"] == _slot(2026, 6, 24, 20)
    assert resolved[0]["price_buy"] == 15.5


def test_resolve_market_slots_supports_variable_length():
    start = datetime(2026, 6, 24, 8, 0, 0)
    target_hours = [start + timedelta(hours=i) for i in range(36)]
    market_data = [
        _market_entry(start + timedelta(hours=i), 10.0 + i)
        for i in range(36)
    ]

    resolved = resolve_market_slots(market_data, target_hours)

    assert len(resolved) == 36
    assert all(slot["price_source"] == PRICE_SOURCE_DAY_AHEAD for slot in resolved)


def test_index_market_data_averages_duplicate_slots():
    slot = datetime(2026, 6, 24, 8, 0, 0)
    indexed = index_market_data_by_slot([
        _market_entry(slot, 10.0),
        _market_entry(slot, 20.0),
    ])
    assert indexed[normalize_price_slot(slot)]["price_buy"] == 15.0


def test_awattar_fetch_window_accepts_timezone_aware_planning_end():
    from zoneinfo import ZoneInfo

    from data.market_prices import MAX_MIRROR_LOOKBACK_DAYS, awattar_fetch_window

    tz = ZoneInfo("Europe/Vienna")
    now_slot = datetime.now(tz).replace(minute=0, second=0, microsecond=0)
    planning_end = now_slot + timedelta(hours=24, minutes=19)
    start, end = awattar_fetch_window(planning_end)
    assert end.tzinfo is not None
    assert end >= datetime.now(tz).replace(minute=0, second=0, microsecond=0)
    assert start.tzinfo == end.tzinfo
    today_midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    assert start == today_midnight - timedelta(days=MAX_MIRROR_LOOKBACK_DAYS)


def test_resolve_market_slots_matches_aware_target_with_naive_market_data():
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Vienna")
    slot = datetime(2026, 7, 4, 9, 0, tzinfo=tz)
    target_hours = [slot]
    market_data = [_market_entry(datetime(2026, 7, 4, 9, 0, 0), 12.34)]

    resolved = resolve_market_slots(market_data, target_hours)

    assert len(resolved) == 1
    assert resolved[0]["price_source"] == PRICE_SOURCE_DAY_AHEAD
    assert resolved[0]["price_buy"] == 12.34


def test_hourly_market_expands_onto_quarter_hour_targets():
    """CH / aWATTar hourly samples fill :15/:30/:45 via parent-hour expand."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Vienna")
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=tz)
    targets = [
        hour,
        hour + timedelta(minutes=15),
        hour + timedelta(minutes=30),
        hour + timedelta(minutes=45),
    ]
    market_data = [_market_entry(datetime(2026, 7, 4, 9, 0, 0), 11.0)]
    resolved = resolve_market_slots(market_data, targets)
    assert len(resolved) == 4
    assert all(slot["price_buy"] == 11.0 for slot in resolved)
    assert all(slot["price_source"] == PRICE_SOURCE_DAY_AHEAD for slot in resolved)


def test_hourly_settlement_epex_values_averages_per_clock_hour():
    """EPEX SDAC 'average rule': all 4 QH quarters get the hour's arithmetic mean."""
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=VIENNA)
    slots = [hour + timedelta(minutes=15 * i) for i in range(4)]
    values = [10.0, 20.0, 30.0, 40.0]

    averaged = hourly_settlement_epex_values(values, slots)

    assert averaged == [25.0, 25.0, 25.0, 25.0]


def test_hourly_settlement_epex_values_keeps_hours_independent():
    slots = [
        datetime(2026, 7, 4, 9, 0, tzinfo=VIENNA),
        datetime(2026, 7, 4, 9, 30, tzinfo=VIENNA),
        datetime(2026, 7, 4, 10, 0, tzinfo=VIENNA),
        datetime(2026, 7, 4, 10, 30, tzinfo=VIENNA),
    ]
    values = [10.0, 30.0, 100.0, 200.0]

    averaged = hourly_settlement_epex_values(values, slots)

    assert averaged == [20.0, 20.0, 150.0, 150.0]


def test_hourly_settlement_epex_values_passes_through_none():
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=VIENNA)
    slots = [hour, hour + timedelta(minutes=15)]

    averaged = hourly_settlement_epex_values([10.0, None], slots)

    assert averaged == [10.0, None]
