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


def test_awattar_import_requires_tariff_fields():
    tariff = {"type": "awattar"}
    with pytest.raises(ValueError, match="fix_aufschlag_cent"):
        import_cent_kwh(10.0, tariff)


def test_awattar_import_uses_tariff_spec():
    tariff = {
        "type": "awattar",
        "netzverlust_faktor": 1.03,
        "fix_aufschlag_cent": 1.5,
        "mwst_austria_faktor": 1.2,
    }
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


def test_dynamic_epex_export_uses_tariff_spec():
    tariff = {
        "type": "dynamic_epex",
        "feed_in_fee_factor": 0.19,
        "feed_in_fix_cent": 0.0,
    }
    # 10 - 0.19 * 10 = 8.1
    assert export_cent_kwh(10.0, tariff) == pytest.approx(8.1)


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


def test_monthly_float_export_uses_lookup():
    from datetime import datetime

    tariff = {
        "type": "monthly_float",
        "arbeitspreis_kwh_cent": 7.15,
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
