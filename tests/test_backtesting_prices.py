"""Tests für Backtesting-Preisstrategien (grüne Zone)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data.backtesting_prices import (
    BacktestingPriceContext,
    build_market_data_as_of,
    import_brutto_cent_for_slots,
    last_day_ahead_calendar_date,
    matrix_prices_from_context,
    slot_in_market_data_as_of,
)
from data.market_prices import (
    PRICE_SOURCE_DAY_AHEAD,
    PRICE_SOURCE_MIRRORED,
    PRICE_SOURCE_PREDICTED,
    resolve_market_slots,
)
from data.price_forecast_model import fit_price_model
from tests.test_price_forecast_model import _synthetic_frame

VIENNA = ZoneInfo("Europe/Vienna")


def test_last_day_ahead_before_noon_same_day():
    moment = datetime(2025, 7, 6, 8, 0, tzinfo=VIENNA)
    assert last_day_ahead_calendar_date(moment) == datetime(2025, 7, 6).date()


def test_last_day_ahead_after_noon_includes_tomorrow():
    moment = datetime(2025, 7, 6, 14, 0, tzinfo=VIENNA)
    assert last_day_ahead_calendar_date(moment) == datetime(2025, 7, 7).date()


def test_build_market_data_excludes_unpublished_future_day_ahead():
    planning = datetime(2025, 7, 6, 8, 0, tzinfo=VIENNA)
    index = pd.date_range("2025-07-05", periods=96, freq="h", tz=VIENNA)
    prices = pd.DataFrame({"price_cent_kwh": [10.0] * len(index)}, index=index)
    market = build_market_data_as_of(prices, planning)
    slots = {entry["timestamp"].date() for entry in market}
    assert datetime(2025, 7, 7).date() not in slots
    assert datetime(2025, 7, 6).date() in slots


def test_resolve_market_slots_forecast_uses_model():
    frame = _synthetic_frame(hours=96)
    model = fit_price_model(frame.iloc[:72])
    planning = datetime(2025, 7, 3, 8, 0, tzinfo=VIENNA)
    market = build_market_data_as_of(
        frame.rename(columns={"price_epex_cent_kwh": "price_cent_kwh"}),
        planning,
    )
    target = datetime(2025, 7, 4, 18, 0, tzinfo=VIENNA)
    feature_frame = frame.copy()
    feature_frame.index = feature_frame.index.tz_convert(VIENNA).tz_localize(None)
    resolved = resolve_market_slots(
        market,
        [target],
        missing_price_strategy="forecast",
        forecast_model=model,
        forecast_feature_frame=feature_frame,
    )
    assert len(resolved) == 1
    assert resolved[0]["price_source"] == PRICE_SOURCE_PREDICTED


def test_matrix_prices_mirror_marks_extrapolated_slots():
    planning = datetime(2025, 7, 6, 8, 0, tzinfo=VIENNA)
    index = pd.date_range("2025-07-01", periods=240, freq="h", tz=VIENNA)
    prices = pd.DataFrame(
        {"price_cent_kwh": [5.0 + (i % 24) for i in range(len(index))]},
        index=index,
    )
    slots = [datetime(2025, 7, 8, h, 0, tzinfo=VIENNA) for h in range(3)]
    ctx = BacktestingPriceContext(
        strategy="mirror",
        planning_moment=planning,
    )
    _, _, sources = matrix_prices_from_context(prices, slots, ctx)
    assert sources == [PRICE_SOURCE_MIRRORED] * 3


def test_import_brutto_cent_hourly_settlement_averages_quarters():
    """Tariffs with settlement_mtu='60min' bill the hour's EPEX mean, not each QH price."""
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=VIENNA)
    slots = [hour + timedelta(minutes=15 * i) for i in range(4)]
    epex_values = [10.0, 20.0, 30.0, 40.0]  # mean = 25.0
    tariff = {
        "type": "spot_hourly",
        "land": "AT",
        "settlement_fee_cent_kwh": 0.0,
        "markup_percent": 0.0,
        "prices_include_vat": False,
        "vat_percent": 0.0,
        "settlement_mtu": "60min",
    }
    brutto = import_brutto_cent_for_slots(epex_values, slots, import_tariff_spec=tariff)
    assert brutto == [pytest.approx(25.0)] * 4


def test_import_brutto_cent_quarter_hour_settlement_keeps_per_slot_prices():
    """No settlement_mtu (or '15min') keeps today's per-QH behaviour — regression guard."""
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=VIENNA)
    slots = [hour + timedelta(minutes=15 * i) for i in range(4)]
    epex_values = [10.0, 20.0, 30.0, 40.0]
    tariff = {
        "type": "spot_hourly",
        "land": "AT",
        "settlement_fee_cent_kwh": 0.0,
        "markup_percent": 0.0,
        "prices_include_vat": False,
        "vat_percent": 0.0,
    }
    brutto = import_brutto_cent_for_slots(epex_values, slots, import_tariff_spec=tariff)
    assert brutto == [pytest.approx(v) for v in epex_values]
