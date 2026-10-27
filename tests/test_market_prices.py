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
    index_market_data_by_slot,
    normalize_price_slot,
    price_source_for_method,
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


def test_mirror_takes_an_hourly_sample_of_an_earlier_day():
    """Hourly history (old CSV / CH) fills all four quarter-hours of its hour as mirror source."""
    market_data = [_market_entry(datetime(2026, 6, 23, 20, 0, 0), 7.0)]
    targets = [datetime(2026, 6, 25, 20, 45, tzinfo=VIENNA)]

    resolved = resolve_market_slots(market_data, targets)

    assert resolved[0]["price_source"] == PRICE_SOURCE_MIRRORED
    assert resolved[0]["price_buy"] == 7.0


def test_mirror_keeps_the_wall_clock_time_across_the_spring_dst_change():
    """2026-03-29 has 23 hours: 10:00 on 03-30 mirrors 10:00 on 03-28, not 11:00."""
    market_data = [
        _market_entry(datetime(2026, 3, 28, 10, 0, tzinfo=VIENNA), 10.0),
        _market_entry(datetime(2026, 3, 28, 11, 0, tzinfo=VIENNA), 11.0),
    ]
    targets = [datetime(2026, 3, 30, 10, 0, tzinfo=VIENNA)]

    resolved = resolve_market_slots(market_data, targets)

    assert resolved[0]["price_buy"] == 10.0


def test_price_source_follows_the_edibert_method():
    assert price_source_for_method("exact") == PRICE_SOURCE_DAY_AHEAD
    assert price_source_for_method("mirror") == PRICE_SOURCE_MIRRORED
    assert price_source_for_method("ols") == PRICE_SOURCE_PREDICTED
    with pytest.raises(ValueError, match="hold"):
        price_source_for_method("hold")


def test_index_market_data_averages_duplicate_slots():
    slot = datetime(2026, 6, 24, 8, 0, 0)
    indexed = index_market_data_by_slot([
        _market_entry(slot, 10.0),
        _market_entry(slot, 20.0),
    ])
    assert indexed[normalize_price_slot(slot)]["price_buy"] == 15.0


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


def test_resolve_market_slots_leaves_retail_price_to_the_tariff():
    """Since Edibert P3b the slots carry only market prices; k_act is priced per list."""
    slot = normalize_price_slot(datetime(2026, 9, 29, 10, 0, tzinfo=VIENNA))
    out = resolve_market_slots([{"timestamp": slot, "price_buy": 12.5}], [slot])
    assert out[0]["price_buy"] == 12.5
    assert "k_act" not in out[0]


def test_predicted_and_day_ahead_slots_carry_same_fields():
    """Predicted slots look like day-ahead slots (price_buy, no k_act) for the tariff step."""
    from unittest.mock import MagicMock, patch

    da_slot = normalize_price_slot(datetime(2025, 7, 1, 10, 0, tzinfo=VIENNA))
    pred_slot = normalize_price_slot(datetime(2025, 7, 2, 18, 0, tzinfo=VIENNA))
    epex = 8.0
    market = [{"timestamp": da_slot, "price_buy": epex}]
    feature_frame = pd.DataFrame(
        {"intercept": [1.0]},
        index=pd.DatetimeIndex([pred_slot.replace(tzinfo=None)]),
    )
    model = MagicMock()
    with patch("data.ols_forecaster.OlsForecaster._predict", return_value=epex):
        out = resolve_market_slots(
            market,
            [da_slot, pred_slot],
            missing_price_strategy="forecast",
            forecast_model=model,
            forecast_feature_frame=feature_frame,
            # Live bias fetches Open-Meteo archive weather (network, minutes).
            live_bias_enabled=False,
        )
    by_src = {row["price_source"]: row for row in out}
    assert by_src[PRICE_SOURCE_DAY_AHEAD]["price_buy"] == pytest.approx(epex)
    assert by_src[PRICE_SOURCE_PREDICTED]["price_buy"] == pytest.approx(epex)
    assert all("k_act" not in row for row in out)


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
            "data.ols_forecaster.OlsForecaster._predict",
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
                )
    by_src = {row["price_source"]: row for row in out}
    assert by_src[PRICE_SOURCE_DAY_AHEAD]["price_buy"] == pytest.approx(10.0)
    assert by_src[PRICE_SOURCE_PREDICTED]["price_buy"] == pytest.approx(6.25)
    assert by_src[PRICE_SOURCE_PREDICTED]["live_bias_cent_kwh"] == pytest.approx(1.25)
