"""Tests für Day-Ahead-Auflösung und Spiegel-Extrapolation."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from data.market_prices import (
    PRICE_SOURCE_DAY_AHEAD,
    PRICE_SOURCE_MIRRORED,
    index_market_data_by_slot,
    resolve_24h_market_slots,
)


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
    assert resolved[-1]["mirrored_from"] == datetime(2026, 6, 24, 9, 0, 0)
    assert resolved[-1]["price_buy"] == 9.0


def test_resolve_24h_raises_when_mirror_source_missing():
    start = datetime(2026, 6, 24, 10, 0, 0)
    target_hours = [start + timedelta(hours=i) for i in range(24)]
    market_data = [_market_entry(start, 12.0)]

    with pytest.raises(ValueError, match="Spiegelquelle"):
        resolve_24h_market_slots(market_data, target_hours)


def test_index_market_data_averages_duplicate_slots():
    slot = datetime(2026, 6, 24, 8, 0, 0)
    indexed = index_market_data_by_slot([
        _market_entry(slot, 10.0),
        _market_entry(slot, 20.0),
    ])
    assert indexed[slot]["price_buy"] == 15.0
