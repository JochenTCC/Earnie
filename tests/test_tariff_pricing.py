"""Tests für DACH-Tarifpreise (Version 1.24.f)."""
from __future__ import annotations

import pytest

from data.tariff_pricing import export_cent_kwh, import_cent_kwh, market_zone_for_land


def test_market_zone_for_land():
    assert market_zone_for_land("AT") == "AT"
    assert market_zone_for_land("DE") == "DE-LU"
    assert market_zone_for_land("CH") == "CH"


def test_spot_import_with_markup_and_settlement():
    tariff = {
        "type": "spot_hourly",
        "land": "DE",
        "settlement_fee_cent_kwh": 2.25,
        "markup_percent": 3.0,
        "prices_include_vat": False,
        "vat_percent": 19.0,
    }
    # (8.5 * 1.03 + 2.25) * 1.19
    result = import_cent_kwh(8.5, tariff)
    assert result == pytest.approx(13.096, rel=1e-4)


def test_spot_import_de_netzentgelt_override():
    tariff = {
        "type": "spot_hourly",
        "land": "DE",
        "settlement_fee_cent_kwh": 1.0,
        "markup_percent": 0.0,
        "prices_include_vat": True,
        "vat_percent": 19.0,
    }
    assert import_cent_kwh(10.0, tariff, netzentgelt_override=5.0) == pytest.approx(16.0)


def test_fixed_import_includes_vat():
    tariff = {
        "type": "fixed_cent",
        "fix_cent_kwh": 10.0,
        "prices_include_vat": False,
        "vat_percent": 20.0,
    }
    assert import_cent_kwh(99.0, tariff) == pytest.approx(12.0)


def test_spot_export_minus_settlement():
    tariff = {
        "type": "spot_hourly",
        "land": "AT",
        "settlement_fee_cent_kwh": 1.0,
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    assert export_cent_kwh(8.5, tariff) == pytest.approx(7.5)


def test_ch_fixed_export():
    tariff = {
        "type": "fixed",
        "land": "CH",
        "k_push_cent": 12.5,
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    assert export_cent_kwh(None, tariff) == pytest.approx(12.5)


def test_awattar_at_import_as_spot_hourly():
    tariff = {
        "type": "spot_hourly",
        "land": "AT",
        "settlement_fee_cent_kwh": 1.5,
        "markup_percent": 3.0,
        "prices_include_vat": False,
        "vat_percent": 20.0,
    }
    # (10.0 * 1.03 + 1.5) * 1.2
    assert import_cent_kwh(10.0, tariff) == pytest.approx(14.16)


def test_import_monthly_table_uses_slot_month():
    from datetime import datetime

    tariff = {
        "type": "monthly_table",
        "monthly_rates": [
            {"year": 2025, "month": 6, "tariff_cent_kwh": 18.0},
            {"year": 2025, "month": 12, "tariff_cent_kwh": 24.0},
        ],
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    slot = datetime(2025, 6, 15, 12, 0)
    assert import_cent_kwh(99.0, tariff, slot_datetime=slot) == pytest.approx(18.0)


def test_import_monthly_table_accepts_normalized_triples():
    from datetime import datetime

    tariff = {
        "type": "monthly_table",
        "monthly_rates": ((2025, 6, 18.0), (2025, 12, 24.0)),
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    slot = datetime(2025, 12, 1, 0, 0)
    assert import_cent_kwh(99.0, tariff, slot_datetime=slot) == pytest.approx(24.0)


def test_spot_export_with_fee_factor_matches_sunny_spot():
    tariff = {
        "type": "spot_hourly",
        "land": "AT",
        "settlement_fee_cent_kwh": 0.0,
        "feed_in_fee_factor": 0.19,
        "feed_in_fix_cent": 0.0,
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    # 10 - 0.19 * 10 = 8.1
    assert export_cent_kwh(10.0, tariff) == pytest.approx(8.1)


def test_spot_export_fee_zero_plus_settlement():
    tariff = {
        "type": "spot_hourly",
        "land": "AT",
        "settlement_fee_cent_kwh": 1.2,
        "feed_in_fee_factor": 0.0,
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    assert export_cent_kwh(8.5, tariff) == pytest.approx(7.3)


def test_de_spot_ch_fix_scenario_pricing():
    """Abnahme 1.24.f: DE-Spot Bezug + CH-Fix Einspeise."""
    import_tariff = {
        "type": "spot_hourly",
        "land": "DE",
        "settlement_fee_cent_kwh": 2.25,
        "markup_percent": 3.0,
        "prices_include_vat": False,
        "vat_percent": 19.0,
    }
    export_tariff = {
        "type": "fixed",
        "land": "CH",
        "k_push_cent": 12.5,
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    epex = 8.5
    k_act = import_cent_kwh(epex, import_tariff)
    k_push_act = export_cent_kwh(epex, export_tariff)
    assert k_act == pytest.approx(13.096, rel=1e-4)
    assert k_push_act == pytest.approx(12.5)


def test_monthly_table_export_uses_lookup():
    from datetime import datetime

    tariff = {
        "type": "monthly_table",
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    lookup = {(2026, 6): 6.772}
    slot = datetime(2026, 6, 1, 0, 0)
    assert export_cent_kwh(
        None,
        tariff,
        slot_datetime=slot,
        monthly_lookup=lookup,
    ) == pytest.approx(6.772)


def test_lookup_monthly_cent_exact():
    from data.tariff_pricing import lookup_monthly_cent

    cent, source = lookup_monthly_cent({(2026, 7): 5.0}, 2026, 7)
    assert cent == pytest.approx(5.0)
    assert source is None


def test_lookup_monthly_cent_prefers_prior_year_over_prior_month():
    from data.tariff_pricing import FALLBACK_PRIOR_YEAR, lookup_monthly_cent

    lookup = {(2025, 7): 4.0, (2026, 6): 9.0}
    cent, source = lookup_monthly_cent(lookup, 2026, 7)
    assert cent == pytest.approx(4.0)
    assert source == FALLBACK_PRIOR_YEAR


def test_lookup_monthly_cent_falls_back_to_prior_month():
    from data.tariff_pricing import FALLBACK_PRIOR_MONTH, lookup_monthly_cent

    lookup = {(2026, 6): 7.5}
    cent, source = lookup_monthly_cent(lookup, 2026, 7)
    assert cent == pytest.approx(7.5)
    assert source == FALLBACK_PRIOR_MONTH


def test_lookup_monthly_cent_january_uses_december_prior_year_month():
    from data.tariff_pricing import FALLBACK_PRIOR_MONTH, lookup_monthly_cent

    lookup = {(2025, 12): 3.1}
    cent, source = lookup_monthly_cent(lookup, 2026, 1)
    assert cent == pytest.approx(3.1)
    assert source == FALLBACK_PRIOR_MONTH


def test_lookup_monthly_cent_raises_when_no_fallback():
    from data.tariff_pricing import lookup_monthly_cent

    with pytest.raises(ValueError, match="Kein Monatseintrag für 2026-07"):
        lookup_monthly_cent({(2024, 1): 1.0}, 2026, 7)


def test_import_monthly_table_uses_prior_year_fallback():
    from datetime import datetime

    tariff = {
        "type": "monthly_table",
        "monthly_rates": [
            {"year": 2025, "month": 8, "tariff_cent_kwh": 19.5},
            {"year": 2025, "month": 7, "tariff_cent_kwh": 18.0},
        ],
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    slot = datetime(2026, 8, 15, 12, 0)
    assert import_cent_kwh(99.0, tariff, slot_datetime=slot) == pytest.approx(19.5)


def test_export_monthly_table_uses_prior_month_fallback():
    from datetime import datetime

    from data.tariff_pricing import FALLBACK_PRIOR_MONTH, lookup_monthly_cent

    lookup = {(2026, 7): 6.1}
    cent, source = lookup_monthly_cent(lookup, 2026, 8, label="Export-Tarif")
    assert cent == pytest.approx(6.1)
    assert source == FALLBACK_PRIOR_MONTH
    tariff = {
        "type": "monthly_table",
        "prices_include_vat": True,
        "vat_percent": 0.0,
    }
    slot = datetime(2026, 8, 1, 0, 0)
    assert export_cent_kwh(
        None,
        tariff,
        slot_datetime=slot,
        monthly_lookup=lookup,
    ) == pytest.approx(6.1)


def test_monthly_rates_cover_month():
    from data.tariff_pricing import monthly_rates_cover_month

    tariff = {
        "type": "monthly_table",
        "monthly_rates": [{"year": 2026, "month": 6, "tariff_cent_kwh": 5.0}],
    }
    assert monthly_rates_cover_month(tariff, 2026, 6) is True
    assert monthly_rates_cover_month(tariff, 2026, 7) is False
    assert monthly_rates_cover_month({"type": "fixed", "k_push_cent": 1.0}, 2026, 7) is True


def test_lookup_monthly_cent_logs_fallback_once(caplog):
    import logging

    import data.tariff_pricing as pricing

    pricing._logged_monthly_fallbacks.clear()
    lookup = {(2025, 8): 4.0}
    with caplog.at_level(logging.WARNING, logger="data.tariff_pricing"):
        pricing.lookup_monthly_cent(lookup, 2026, 8, label="Export-Tarif")
        pricing.lookup_monthly_cent(lookup, 2026, 8, label="Export-Tarif")
    messages = [
        r.message
        for r in caplog.records
        if "Kein Monatseintrag für 2026-08" in r.message
    ]
    assert len(messages) == 1


def test_missing_next_month_tariff_hints():
    from data.tariff_pricing import missing_next_month_tariff_hints

    export = {
        "id": "oemag",
        "label": "OeMAG",
        "type": "monthly_table",
        "monthly_rates": [{"year": 2026, "month": 6, "tariff_cent_kwh": 5.0}],
    }
    hints = missing_next_month_tariff_hints(
        import_tariff={"type": "fixed_cent", "fix_cent_kwh": 30.0},
        export_tariff=export,
        year=2026,
        month=8,
    )
    assert hints == ["Einspeise: OeMAG"]


def test_is_within_days_of_next_month():
    from datetime import date

    from data.tariff_pricing import is_within_days_of_next_month

    assert is_within_days_of_next_month(date(2026, 1, 29), days=2) is False
    assert is_within_days_of_next_month(date(2026, 1, 30), days=2) is True
    assert is_within_days_of_next_month(date(2026, 1, 31), days=2) is True
    assert is_within_days_of_next_month(date(2026, 2, 26), days=2) is False
    assert is_within_days_of_next_month(date(2026, 2, 27), days=2) is True
    assert is_within_days_of_next_month(date(2026, 2, 28), days=2) is True
    assert is_within_days_of_next_month(date(2024, 2, 27), days=2) is False
    assert is_within_days_of_next_month(date(2024, 2, 28), days=2) is True
    assert is_within_days_of_next_month(date(2024, 2, 29), days=2) is True
