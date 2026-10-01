"""Tests für Day-Ahead-Auflösung und Spiegel-Extrapolation."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from zoneinfo import ZoneInfo

from data.market_prices import (
    PRICE_SOURCE_DAY_AHEAD,
    PRICE_SOURCE_MIRRORED,
    PRICE_SOURCE_PREDICTED,
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


def test_resolve_market_slots_monthly_table_passes_slot_datetime():
    from unittest.mock import patch

    from data.tariff_pricing import import_cent_kwh

    slot = normalize_price_slot(datetime(2026, 9, 29, 10, 0, tzinfo=VIENNA))
    market = [{"timestamp": slot, "price_buy": 12.5}]
    monthly_spec = {
        "type": "monthly_table",
        "id": "debug_monthly",
        "prices_include_vat": True,
        "vat_percent": 20.0,
        "monthly_rates": [[2026, 9, 25.0]],
    }
    resolved_settings = {
        "_import_tariff_spec": monthly_spec,
        "import_tariff_id": "debug_monthly",
    }
    expected = import_cent_kwh(12.5, monthly_spec, slot_datetime=slot)
    with patch("config.get_resolved_runtime_settings", return_value=resolved_settings):
        out = resolve_market_slots(market, [slot])
    assert out[0]["k_act"] == expected


def test_predicted_and_day_ahead_same_tariff_extras_for_equal_epex():
    """Regression: predicted k_act uses same import formula as day_ahead."""
    from unittest.mock import MagicMock, patch

    from data.tariff_pricing import import_cent_kwh

    da_slot = normalize_price_slot(datetime(2025, 7, 1, 10, 0, tzinfo=VIENNA))
    pred_slot = normalize_price_slot(datetime(2025, 7, 2, 18, 0, tzinfo=VIENNA))
    epex = 8.0
    market = [{"timestamp": da_slot, "price_buy": epex}]
    spot_spec = {
        "type": "spot_hourly",
        "id": "debug_spot",
        "settlement_fee_cent_kwh": 1.5,
        "markup_percent": 3.0,
        "prices_include_vat": False,
        "vat_percent": 20.0,
    }
    resolved_settings = {
        "_import_tariff_spec": spot_spec,
        "import_tariff_id": "debug_spot",
        "netzentgelt_cent_kwh": 2.0,
    }
    expected = import_cent_kwh(
        epex,
        spot_spec,
        netzentgelt_override=2.0,
        slot_datetime=pred_slot,
    )
    feature_frame = pd.DataFrame(
        {"intercept": [1.0]},
        index=pd.DatetimeIndex([pred_slot.replace(tzinfo=None)]),
    )
    model = MagicMock()
    with patch("config.get_resolved_runtime_settings", return_value=resolved_settings):
        with patch(
            "data.market_prices._lookup_forecast_epex",
            return_value=epex,
        ):
            out = resolve_market_slots(
                market,
                [da_slot, pred_slot],
                missing_price_strategy="forecast",
                forecast_model=model,
                forecast_feature_frame=feature_frame,
            )
    by_src = {row["price_source"]: row for row in out}
    assert by_src[PRICE_SOURCE_DAY_AHEAD]["k_act"] == pytest.approx(expected)
    assert by_src[PRICE_SOURCE_PREDICTED]["k_act"] == pytest.approx(expected)
    assert by_src[PRICE_SOURCE_PREDICTED]["price_buy"] == pytest.approx(epex)


def test_resolve_market_slots_applies_live_bias_to_predicted_only():
    from unittest.mock import MagicMock, patch

    da_slot = normalize_price_slot(datetime(2025, 7, 1, 10, 0, tzinfo=VIENNA))
    pred_slot = normalize_price_slot(datetime(2025, 7, 2, 18, 0, tzinfo=VIENNA))
    market = [{"timestamp": da_slot, "price_buy": 10.0}]
    feature_frame = pd.DataFrame(
        {"intercept": [1.0]},
        index=pd.DatetimeIndex([pred_slot.replace(tzinfo=None)]),
    )
    spot_spec = {
        "type": "spot_hourly",
        "id": "debug_spot",
        "settlement_fee_cent_kwh": 0.0,
        "markup_percent": 0.0,
        "prices_include_vat": True,
        "vat_percent": 20.0,
    }
    resolved_settings = {
        "_import_tariff_spec": spot_spec,
        "import_tariff_id": "debug_spot",
    }
    with patch("config.get_resolved_runtime_settings", return_value=resolved_settings):
        with patch(
            "data.market_prices._lookup_forecast_epex",
            return_value=5.0,
        ):
            with patch(
                "data.market_prices._resolve_live_bias_cent",
                return_value=1.25,
            ):
                out = resolve_market_slots(
                    market,
                    [da_slot, pred_slot],
                    missing_price_strategy="forecast",
                    forecast_model=MagicMock(),
                    forecast_feature_frame=feature_frame,
                    live_bias_enabled=True,
                    eu_power_live_source="energy_charts_forecast",
                )
    by_src = {row["price_source"]: row for row in out}
    assert by_src[PRICE_SOURCE_DAY_AHEAD]["price_buy"] == pytest.approx(10.0)
    assert by_src[PRICE_SOURCE_PREDICTED]["price_buy"] == pytest.approx(6.25)
    assert by_src[PRICE_SOURCE_PREDICTED]["live_bias_cent_kwh"] == pytest.approx(1.25)
    assert by_src[PRICE_SOURCE_PREDICTED]["eu_power_live_source"] == (
        "energy_charts_forecast"
    )
