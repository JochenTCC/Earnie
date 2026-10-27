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
    resolve_backtesting_slot_prices,
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


def test_build_market_data_not_before_drops_only_older_rows():
    planning = datetime(2025, 7, 10, 8, 0)
    index = pd.date_range("2025-06-20", "2025-07-12 23:45", freq="15min")
    prices = pd.DataFrame({"price_cent_kwh": range(len(index))}, index=index)
    full = build_market_data_as_of(prices, planning)
    not_before = datetime(2025, 7, 1, 6, 0, tzinfo=VIENNA)
    sliced = build_market_data_as_of(prices, planning, not_before=not_before)
    assert sliced == [row for row in full if row["timestamp"] >= not_before - timedelta(hours=1)]
    assert sliced[0]["timestamp"] == datetime(2025, 7, 1, 5, 0, tzinfo=VIENNA)


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
        # Live bias fetches Open-Meteo archive weather (network, minutes).
        live_bias_enabled=False,
    )
    assert len(resolved) == 1
    assert resolved[0]["price_source"] == PRICE_SOURCE_PREDICTED


def test_se_forecast_live_bias_reads_training_frame_not_network():
    """The SE takes the bias lookback features from its training frame (no Energy-Charts fetch)."""
    from unittest.mock import patch

    from data.price_forecast_live import compute_rolling_epex_bias_cent

    frame = _synthetic_frame(hours=96)
    model = fit_price_model(frame.iloc[:72])
    planning = datetime(2025, 7, 3, 8, 0, tzinfo=VIENNA)
    prices = frame.rename(columns={"price_epex_cent_kwh": "price_cent_kwh"})
    feature_frame = frame.copy()
    feature_frame.index = feature_frame.index.tz_convert(VIENNA).tz_localize(None)
    ctx = BacktestingPriceContext(
        strategy="forecast",
        planning_moment=planning,
        feature_frame=feature_frame,
        forecast_model=model,
    )
    target = datetime(2025, 7, 4, 18, 0, tzinfo=VIENNA)
    with patch(
        "data.price_forecast_live.build_live_feature_frame_for_slots",
        side_effect=AssertionError("SE must not fetch live features"),
    ):
        rows = resolve_backtesting_slot_prices(prices, [target], ctx)
        market = {
            row["timestamp"]: row["price_buy"]
            for row in build_market_data_as_of(prices, planning)
        }
        want, samples = compute_rolling_epex_bias_cent(
            market,
            forecast_model=model,
            reference_slot=target,
            lookback_hours=48,
            cap_cent_kwh=12.0,
            feature_frame=feature_frame,
        )
    assert samples >= 6 and want is not None
    assert rows[0]["price_source"] == PRICE_SOURCE_PREDICTED
    assert rows[0]["live_bias_cent_kwh"] == pytest.approx(want)


def test_matrix_prices_mirror_marks_extrapolated_slots(tmp_path):
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
    _, _, sources = matrix_prices_from_context(
        prices, slots, ctx, edibert_pricing=_spot_ref(tmp_path, {})
    )
    assert sources == [PRICE_SOURCE_MIRRORED] * 3


def _spot_ref(tmp_path, extra: dict) -> dict:
    """Pricing reference of a net spot import tariff without fees (Edibert format)."""
    import json

    from data.edibert_slot_prices import pricing_reference

    tariff = {
        "id": "spot", "label": "Spot", "type": "spot_hourly", "land": "AT", "supplier_id": "test",
        "settlement_fee_cent_kwh": 0.0, "markup_percent": 0.0,
        "prices_include_vat": False, "vat_percent": 0.0, **extra,
    }
    path = tmp_path / "tariffs.json"
    path.write_text(
        json.dumps({"tariff_format": 1, "import_tariffs": [tariff], "export_tariffs": []}),
        encoding="utf-8",
    )
    return pricing_reference(
        tariffs_path=str(path), grid_fees_path=None, import_tariff_id="spot",
        export_tariff_id=None, timezone_name="Europe/Vienna", profile={"land": "AT"},
    )


def test_import_brutto_cent_hourly_settlement_averages_quarters(tmp_path):
    """Tariffs with settlement_mtu='60min' bill the hour's EPEX mean, not each QH price."""
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=VIENNA)
    slots = [hour + timedelta(minutes=15 * i) for i in range(4)]
    epex_values = [10.0, 20.0, 30.0, 40.0]  # mean = 25.0
    ref = _spot_ref(tmp_path, {"settlement_mtu": "60min"})
    brutto = import_brutto_cent_for_slots(epex_values, slots, edibert_pricing=ref)
    assert brutto == [pytest.approx(25.0)] * 4


def test_import_brutto_cent_quarter_hour_settlement_keeps_per_slot_prices(tmp_path):
    """No settlement_mtu (or '15min') keeps per-QH prices — regression guard."""
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=VIENNA)
    slots = [hour + timedelta(minutes=15 * i) for i in range(4)]
    epex_values = [10.0, 20.0, 30.0, 40.0]
    brutto = import_brutto_cent_for_slots(epex_values, slots, edibert_pricing=_spot_ref(tmp_path, {}))
    assert brutto == [pytest.approx(v) for v in epex_values]
