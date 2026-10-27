"""Tests für die Einspeisevergütung je Slot (Einspeisetarif, bepreist von Edibert)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from data.edibert_slot_prices import EDIBERT_PRICING_KEY, pricing_reference
from data.feed_in_prices import (
    FeedInSettings,
    enrich_matrix_feed_in_prices,
    export_cents_for_slots,
    feed_in_settings_from_dict,
    k_push_act_for_matrix_row,
    validate_fixed_monthly_feed_in_rates,
)

VIENNA = ZoneInfo("Europe/Vienna")


def _settings(tmp_path, tariff: dict) -> FeedInSettings:
    """FeedInSettings with an export tariff file of one entry (Edibert format)."""
    entry = {"label": "Test", "land": "AT", "supplier_id": "test", "vat_percent": 0.0, **tariff}
    path = tmp_path / "tariffs.json"
    path.write_text(
        json.dumps({"tariff_format": 1, "import_tariffs": [], "export_tariffs": [entry]}),
        encoding="utf-8",
    )
    ref = pricing_reference(
        tariffs_path=str(path), grid_fees_path=None, import_tariff_id=None,
        export_tariff_id=entry["id"], timezone_name="Europe/Vienna", profile={"land": "AT"},
    )
    return feed_in_settings_from_dict({"k_push_cent": 0.0, EDIBERT_PRICING_KEY: ref})


def _matrix(prices: list[float]) -> list[dict]:
    hour = datetime(2026, 7, 4, 9, 0, tzinfo=VIENNA)
    return [
        {"hour": hour.hour, "price_buy": price, "slot_datetime": hour + timedelta(minutes=15 * i)}
        for i, price in enumerate(prices)
    ]


def test_feed_in_settings_from_dict_needs_k_push_cent():
    with pytest.raises(KeyError, match="k_push_cent"):
        feed_in_settings_from_dict({})
    settings = feed_in_settings_from_dict({"k_push_cent": 3.7})
    assert settings == FeedInSettings(k_push_cent=3.7, edibert_pricing=None)


def test_spot_export_hourly_settlement_bills_hour_mean(tmp_path):
    """Export tariffs with settlement_mtu='60min' (e.g. SUNNY Spot) bill the hour's EPEX mean."""
    settings = _settings(tmp_path, {
        "id": "sunny", "type": "spot_hourly", "settlement_mtu": "60min",
        "feed_in_fee_factor": 0.19, "prices_include_vat": True,
    })
    matrix = _matrix([10.0, 20.0, 30.0, 40.0])
    enrich_matrix_feed_in_prices(matrix, settings)
    # mean(10,20,30,40) = 25.0 -> 25.0 - 0.19*25.0 = 20.25 for all 4 quarters
    assert [row["k_push_act"] for row in matrix] == [pytest.approx(20.25)] * 4
    # price_buy stays the raw, un-averaged QH value (display/logging field)
    assert [row["price_buy"] for row in matrix] == [10.0, 20.0, 30.0, 40.0]


def test_spot_export_quarter_hour_settlement_keeps_per_slot_prices(tmp_path):
    settings = _settings(tmp_path, {"id": "dyn", "type": "spot_hourly", "prices_include_vat": True})
    matrix = _matrix([10.0, 20.0, 30.0, 40.0])
    enrich_matrix_feed_in_prices(matrix, settings)
    assert [row["k_push_act"] for row in matrix] == [pytest.approx(v) for v in [10.0, 20.0, 30.0, 40.0]]


def test_monthly_table_export_uses_slot_month(tmp_path):
    settings = _settings(tmp_path, {
        "id": "monthly", "type": "monthly_table", "prices_include_vat": True,
        "monthly_rates": [
            {"year": 2026, "month": 6, "tariff_cent_kwh": 3.60},
            {"year": 2026, "month": 7, "tariff_cent_kwh": 6.46},
        ],
    })
    june = datetime(2026, 6, 25, 12, 0)
    july = datetime(2026, 7, 1, 0, 0)
    assert export_cents_for_slots([june, july], [None, None], settings) == [
        pytest.approx(3.60), pytest.approx(6.46)
    ]


def test_export_price_needs_slot_datetime(tmp_path):
    settings = _settings(tmp_path, {"id": "fix", "type": "fixed", "k_push_cent": 3.5,
                                    "prices_include_vat": True})
    with pytest.raises(ValueError, match="slot_datetime"):
        enrich_matrix_feed_in_prices([{"price_buy": 5.0}], settings)


def test_export_price_needs_reference():
    with pytest.raises(ValueError, match="Edibert-Preisreferenz"):
        export_cents_for_slots([datetime(2026, 7, 1, 10)], [5.0], FeedInSettings(k_push_cent=3.5))


def test_k_push_act_for_matrix_row_prefers_matrix_value():
    row = {"k_push_act": 12.5, "k_act": 30.0}
    assert k_push_act_for_matrix_row(row, 3.5) == 12.5


def test_k_push_act_for_matrix_row_uses_fallback():
    row = {"k_act": 30.0}
    assert k_push_act_for_matrix_row(row, 3.5) == 3.5


def test_validate_fixed_monthly_feed_in_rates():
    rates = validate_fixed_monthly_feed_in_rates([
        {"year": 2026, "month": 6, "tariff_cent_kwh": 3.60},
    ])
    assert rates == ((2026, 6, 3.60),)
    with pytest.raises(ValueError, match="doppelter Eintrag"):
        validate_fixed_monthly_feed_in_rates([
            {"year": 2026, "month": 6, "tariff_cent_kwh": 3.60},
            {"year": 2026, "month": 6, "tariff_cent_kwh": 3.70},
        ])
    with pytest.raises(ValueError, match="month muss 1–12"):
        validate_fixed_monthly_feed_in_rates([{"year": 2026, "month": 13, "tariff_cent_kwh": 3.6}])
