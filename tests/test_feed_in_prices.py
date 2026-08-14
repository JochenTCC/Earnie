"""Tests für stündliche vs. fixe Einspeisevergütung."""
from __future__ import annotations

from datetime import datetime

import pytest

from data.feed_in_prices import (
    FEED_IN_MODE_DYNAMIC_EPEX,
    FEED_IN_MODE_FIXED,
    FeedInSettings,
    epex_to_feed_in_cent,
    enrich_matrix_feed_in_prices,
    feed_in_settings_from_dict,
    k_push_act_for_matrix_row,
    resolve_k_push_act,
    validate_feed_in_mode,
    validate_fixed_monthly_feed_in_rates,
)


def test_validate_feed_in_mode_rejects_unknown():
    with pytest.raises(ValueError, match="Unbekannter feed_in_mode"):
        validate_feed_in_mode("hourly_magic")


def test_epex_to_feed_in_cent_sunny_spot_formula():
    assert epex_to_feed_in_cent(10.0, 0.19, 0.0) == pytest.approx(8.1)
    assert epex_to_feed_in_cent(-5.0, 0.19, 0.0) == pytest.approx(-5.95)


def test_fixed_mode_uses_k_push_cent():
    settings = FeedInSettings(
        mode=FEED_IN_MODE_FIXED,
        k_push_cent=3.7,
        fee_factor=0.19,
        fix_cent=0.0,
    )
    assert resolve_k_push_act(100.0, settings) == 3.7
    assert resolve_k_push_act(None, settings) == 3.7


def test_dynamic_mode_requires_epex():
    settings = FeedInSettings(
        mode=FEED_IN_MODE_DYNAMIC_EPEX,
        k_push_cent=3.7,
        fee_factor=0.19,
        fix_cent=0.0,
    )
    assert resolve_k_push_act(10.0, settings) == pytest.approx(8.1)
    with pytest.raises(ValueError, match="price_buy"):
        resolve_k_push_act(None, settings)


def test_feed_in_settings_from_dict_reads_spot_export_fees():
    runtime = {
        "k_push_cent": 3.7,
        "feed_in_mode": "dynamic_epex",
        "_export_tariff_spec": {
            "type": "spot_hourly",
            "feed_in_fee_factor": 0.19,
            "feed_in_fix_cent": 0.0,
        },
    }
    settings = feed_in_settings_from_dict(runtime)
    assert settings.fee_factor == pytest.approx(0.19)
    assert settings.fix_cent == pytest.approx(0.0)


def test_feed_in_settings_spot_without_fee_defaults_zero():
    runtime = {
        "k_push_cent": 3.7,
        "feed_in_mode": "dynamic_epex",
        "_export_tariff_spec": {"type": "spot_hourly"},
    }
    settings = feed_in_settings_from_dict(runtime)
    assert settings.fee_factor == pytest.approx(0.0)
    assert settings.fix_cent == pytest.approx(0.0)


def test_enrich_matrix_feed_in_prices():
    matrix = [
        {"hour": 0, "k_act": 20.0, "price_buy": 10.0, "expected_p_pv": 0.0, "expected_p_act": 1.0},
        {"hour": 1, "k_act": 25.0, "price_buy": 5.0, "expected_p_pv": 0.0, "expected_p_act": 1.0},
    ]
    settings = FeedInSettings(
        mode=FEED_IN_MODE_DYNAMIC_EPEX,
        k_push_cent=3.7,
        fee_factor=0.19,
        fix_cent=0.0,
    )
    enrich_matrix_feed_in_prices(matrix, settings)
    assert matrix[0]["k_push_act"] == pytest.approx(8.1)
    assert matrix[1]["k_push_act"] == pytest.approx(4.05)


def test_k_push_act_for_matrix_row_prefers_matrix_value():
    row = {"k_push_act": 12.5, "k_act": 30.0}
    assert k_push_act_for_matrix_row(row, 3.5) == 12.5


def test_k_push_act_for_matrix_row_uses_fallback():
    row = {"k_act": 30.0}
    assert k_push_act_for_matrix_row(row, 3.5) == 3.5


def test_fixed_mode_uses_monthly_tariff_table():
    tariffs = validate_fixed_monthly_feed_in_rates([
        {"year": 2026, "month": 6, "tariff_cent_kwh": 3.60},
        {"year": 2026, "month": 7, "tariff_cent_kwh": 6.46},
    ])
    settings = FeedInSettings(
        mode=FEED_IN_MODE_FIXED,
        k_push_cent=99.0,
        fee_factor=0.0,
        fix_cent=0.0,
        monthly_fixed_tariffs=tariffs,
    )
    june = datetime(2026, 6, 25, 12, 0)
    july = datetime(2026, 7, 1, 0, 0)
    assert resolve_k_push_act(None, settings, slot_datetime=june) == pytest.approx(3.60)
    assert resolve_k_push_act(None, settings, slot_datetime=july) == pytest.approx(6.46)


def test_fixed_mode_monthly_tariff_requires_slot_datetime():
    tariffs = validate_fixed_monthly_feed_in_rates([
        {"year": 2026, "month": 6, "tariff_cent_kwh": 3.60},
    ])
    settings = FeedInSettings(
        mode=FEED_IN_MODE_FIXED,
        k_push_cent=3.5,
        fee_factor=0.0,
        fix_cent=0.0,
        monthly_fixed_tariffs=tariffs,
    )
    with pytest.raises(ValueError, match="slot_datetime"):
        resolve_k_push_act(None, settings)


def test_enrich_matrix_fixed_mode_uses_slot_month():
    matrix = [
        {
            "hour": 0,
            "k_act": 20.0,
            "expected_p_pv": 1.0,
            "expected_p_act": 1.0,
            "slot_datetime": datetime(2026, 6, 25, 10, 0),
        }
    ]
    tariffs = validate_fixed_monthly_feed_in_rates([
        {"year": 2026, "month": 6, "tariff_cent_kwh": 3.60},
    ])
    settings = FeedInSettings(
        mode=FEED_IN_MODE_FIXED,
        k_push_cent=99.0,
        fee_factor=0.0,
        fix_cent=0.0,
        monthly_fixed_tariffs=tariffs,
    )
    enrich_matrix_feed_in_prices(matrix, settings)
    assert matrix[0]["k_push_act"] == pytest.approx(3.60)


def test_enrich_matrix_feed_in_prices_averages_hourly_settlement():
    """Export tariffs with settlement_mtu='60min' (e.g. SUNNY Spot) bill the hour's EPEX mean."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    vienna = ZoneInfo("Europe/Vienna")
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=vienna)
    matrix = [
        {
            "hour": hour.hour,
            "price_buy": price,
            "slot_datetime": hour + timedelta(minutes=15 * i),
        }
        for i, price in enumerate([10.0, 20.0, 30.0, 40.0])
    ]
    settings = FeedInSettings(
        mode=FEED_IN_MODE_DYNAMIC_EPEX,
        k_push_cent=3.7,
        fee_factor=0.19,
        fix_cent=0.0,
        export_tariff_spec={
            "type": "spot_hourly",
            "settlement_mtu": "60min",
            "feed_in_fee_factor": 0.19,
        },
    )
    enrich_matrix_feed_in_prices(matrix, settings)
    # mean(10,20,30,40) = 25.0 -> 25.0 - 0.19*25.0 = 20.25 for all 4 quarters
    assert [row["k_push_act"] for row in matrix] == [pytest.approx(20.25)] * 4
    # price_buy stays the raw, un-averaged QH value (display/logging field)
    assert [row["price_buy"] for row in matrix] == [10.0, 20.0, 30.0, 40.0]


def test_enrich_matrix_feed_in_prices_quarter_hour_settlement_unaffected():
    """No settlement_mtu (or '15min', e.g. VKW PV-Einspeisetarif Dynamisch) — per-QH prices, no averaging."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    vienna = ZoneInfo("Europe/Vienna")
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=vienna)
    matrix = [
        {
            "hour": hour.hour,
            "price_buy": price,
            "slot_datetime": hour + timedelta(minutes=15 * i),
        }
        for i, price in enumerate([10.0, 20.0, 30.0, 40.0])
    ]
    settings = FeedInSettings(
        mode=FEED_IN_MODE_DYNAMIC_EPEX,
        k_push_cent=3.7,
        fee_factor=0.19,
        fix_cent=0.0,
        export_tariff_spec={"type": "spot_hourly"},
    )
    enrich_matrix_feed_in_prices(matrix, settings)
    assert [row["k_push_act"] for row in matrix] == [
        pytest.approx(v) for v in [10.0, 20.0, 30.0, 40.0]
    ]


def test_fixed_mode_monthly_tariff_falls_back_to_prior_year():
    tariffs = validate_fixed_monthly_feed_in_rates([
        {"year": 2025, "month": 8, "tariff_cent_kwh": 4.2},
        {"year": 2026, "month": 7, "tariff_cent_kwh": 9.9},
    ])
    settings = FeedInSettings(
        mode=FEED_IN_MODE_FIXED,
        k_push_cent=99.0,
        fee_factor=0.0,
        fix_cent=0.0,
        monthly_fixed_tariffs=tariffs,
    )
    august = datetime(2026, 8, 1, 0, 0)
    assert resolve_k_push_act(None, settings, slot_datetime=august) == pytest.approx(4.2)
