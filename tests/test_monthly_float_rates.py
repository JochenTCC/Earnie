"""Tests für monthly_float Einspeisetarife (Version 1.24.g)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from data.monthly_float_rates import (
    REQUIRED_OEMAG_MONTHS,
    build_monthly_float_lookup,
    load_econtrol_referenzmarktwert_pv_monthly,
    load_monthly_float_reference_cent,
    load_oemag_monthly_reference_rates,
)
from data.tariff_pricing import export_cent_kwh


OEMAG_RATES = (
    (2025, 7, 5.965),
    (2025, 8, 5.9),
    (2025, 9, 7.1),
    (2025, 10, 9.008),
    (2025, 11, 8.7),
    (2025, 12, 8.7),
    (2026, 1, 8.842),
    (2026, 2, 8.457),
    (2026, 3, 5.72),
    (2026, 4, 6.772),
    (2026, 5, 6.772),
    (2026, 6, 6.772),
)


def _tariffs_doc() -> dict:
    return {
        "oemag_monthly_feed_in_rates": [
            {"year": y, "month": m, "tariff_cent_kwh": c}
            for y, m, c in OEMAG_RATES
        ],
        "monthly_float_reference_cent_kwh": 7.15,
    }


def test_load_oemag_requires_twelve_months():
    doc = _tariffs_doc()
    rates = load_oemag_monthly_reference_rates(doc)
    assert len(rates) >= REQUIRED_OEMAG_MONTHS


def test_load_oemag_rejects_wrong_count():
    doc = _tariffs_doc()
    doc["oemag_monthly_feed_in_rates"] = doc["oemag_monthly_feed_in_rates"][:6]
    with pytest.raises(ValueError, match="mindestens 12"):
        load_oemag_monthly_reference_rates(doc)


def test_load_oemag_allows_more_than_twelve_months():
    doc = _tariffs_doc()
    extra = {"year": 2025, "month": 6, "tariff_cent_kwh": 5.855}
    doc["oemag_monthly_feed_in_rates"] = [extra, *doc["oemag_monthly_feed_in_rates"]]
    rates = load_oemag_monthly_reference_rates(doc)
    assert len(rates) == 13
    assert rates[0][:2] == (2025, 6)


def test_oemag_identity_scaling():
    tariff = {"arbeitspreis_kwh_cent": 7.15, "settlement_fee_cent_kwh": 0.0}
    lookup = build_monthly_float_lookup(OEMAG_RATES, 7.15, tariff)
    june_2026 = next(item for item in lookup if item[:2] == (2026, 6))
    assert june_2026 == (2026, 6, pytest.approx(6.772))


def test_energie_ag_scaling_with_settlement():
    tariff = {"arbeitspreis_kwh_cent": 5.85, "settlement_fee_cent_kwh": 1.5}
    lookup = build_monthly_float_lookup(OEMAG_RATES, 7.15, tariff)
    expected = max(0.0, 6.772 * 5.85 / 7.15 - 1.5)
    june_2026 = next(item for item in lookup if item[:2] == (2026, 6))
    assert june_2026 == (2026, 6, pytest.approx(expected, rel=1e-4))


def test_export_cent_kwh_monthly_table_from_seed_lookup():
    tariff = {
        "type": "monthly_table",
        "arbeitspreis_kwh_cent": 7.15,
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    lookup = {
        (year, month): cent
        for year, month, cent in build_monthly_float_lookup(OEMAG_RATES, 7.15, tariff)
    }
    slot = datetime(2026, 6, 15, 12, 0)
    assert export_cent_kwh(
        None,
        tariff,
        slot_datetime=slot,
        monthly_lookup=lookup,
    ) == pytest.approx(6.772)


def test_load_econtrol_referenzmarktwert_pv():
    root = Path(__file__).resolve().parents[1]
    import json

    doc = json.loads((root / "share" / "config" / "tariffs.json").read_text(encoding="utf-8"))
    rates = load_econtrol_referenzmarktwert_pv_monthly(doc)
    assert len(rates) >= 12
    june = next(item for item in rates if item[:2] == (2026, 6))
    assert june[2] == pytest.approx(5.55)


def test_load_monthly_float_reference_cent_required():
    with pytest.raises(ValueError, match="monthly_float_reference_cent_kwh"):
        load_monthly_float_reference_cent({})
    assert load_monthly_float_reference_cent(_tariffs_doc()) == pytest.approx(7.15)
