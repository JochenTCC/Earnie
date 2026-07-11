"""Tests für 1.26.0 P3 — Live/Backtesting-Preisparität, P3a-Fenster, P3b-Thermal."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data.backtesting_prices import (
    enrich_slots_import_prices,
    import_brutto_cent_for_slots,
    matrix_prices_from_context,
    pricing_kwargs_from_resolved,
)
from data.data_loader import _monday_of_week, resolve_simulation_window
from data.heating_need import thermal_on_off_hourly_profile, weekly_electric_kwh
from data.market_prices import resolve_market_slots
from house_config.planning_flex_bridge import thermal_hourly_overlay

VIENNA = ZoneInfo("Europe/Vienna")

_LEGACY_AWATTAR = {
    "netzverlust_faktor": 1.03,
    "fix_aufschlag_cent": 1.5,
    "mwst_austria_faktor": 1.2,
}


def _resolved_awattar() -> dict:
    return {
        "_import_tariff_spec": {
            "id": "awattar_at",
            "type": "awattar",
            **{k: v for k, v in _LEGACY_AWATTAR.items()},
        },
        "_export_tariff_spec": {
            "id": "dynamic_epex",
            "type": "dynamic_epex",
            "feed_in_fee_factor": 0.19,
            "feed_in_fix_cent": 0.0,
        },
    }


def _resolved_fixed_import() -> dict:
    return {
        "_import_tariff_spec": {
            "id": "fixed_imp",
            "type": "fixed_cent",
            "fix_cent_kwh": 37.0,
            "prices_include_vat": True,
            "vat_percent": 0.0,
        },
    }


@pytest.mark.parametrize(
    "resolved",
    [_resolved_awattar(), _resolved_fixed_import()],
)
def test_live_and_backtesting_import_prices_match(resolved):
    slots = [datetime(2025, 6, 10, h, 0) for h in range(6)]
    epex = [4.2, 5.1, 6.0, 7.3, 8.0, 3.9]
    kwargs = pricing_kwargs_from_resolved(resolved, {"awattar": _LEGACY_AWATTAR})

    live_brutto = import_brutto_cent_for_slots(epex, slots, **kwargs)
    index = pd.DatetimeIndex(slots)
    prices_df = pd.DataFrame({"price_cent_kwh": epex}, index=index)
    _, bt_brutto, _ = matrix_prices_from_context(
        prices_df,
        slots,
        None,
        **kwargs,
    )
    assert live_brutto == pytest.approx(bt_brutto)


def test_enrich_slots_import_prices_matches_matrix():
    resolved = _resolved_awattar()
    kwargs = pricing_kwargs_from_resolved(resolved, {"awattar": _LEGACY_AWATTAR})
    slots_dt = [datetime(2025, 7, 1, h, 0) for h in (0, 1, 2)]
    market = [
        {"timestamp": slots_dt[0], "price_buy": 10.0},
        {"timestamp": slots_dt[1], "price_buy": 11.0},
        {"timestamp": slots_dt[2], "price_buy": 9.5},
    ]
    resolved_slots = resolve_market_slots(market, slots_dt)
    enrich_slots_import_prices(resolved_slots, slots_dt, **kwargs)
    expected = import_brutto_cent_for_slots(
        [10.0, 11.0, 9.5],
        slots_dt,
        **kwargs,
    )
    assert [slot["k_act"] for slot in resolved_slots] == pytest.approx(expected)


def test_monday_of_week_snaps_to_monday():
    wednesday = pd.Timestamp("2025-07-09")
    monday = _monday_of_week(wednesday)
    assert monday.dayofweek == 0
    assert monday.date().isoformat() == "2025-07-07"


def test_resolve_simulation_window_start_is_monday(monkeypatch):
    monkeypatch.setattr(
        pd.Timestamp,
        "now",
        classmethod(lambda cls, tz=None: pd.Timestamp("2025-07-09")),
    )
    start, end = resolve_simulation_window("last_12_months", "", "")
    assert start.dayofweek == 0
    assert end.normalize() == pd.Timestamp("2025-07-09")


def test_thermal_on_off_uses_nominal_or_zero():
    weekly = [6.0] * 52
    nominal = 3.0
    profile = thermal_on_off_hourly_profile(
        weekly,
        nominal_power_kw=nominal,
        hours_per_year=168,
    )
    assert len(profile) == 168
    for kw in profile:
        assert kw == pytest.approx(0.0) or kw == pytest.approx(nominal)
    hours_per_week = 168 // 52
    assert sum(profile[:hours_per_week]) == pytest.approx(6.0, rel=1e-3)


def test_thermal_on_off_preserves_weekly_kwh():
    params = {
        "living_area_m2": 120.0,
        "building_class": 3,
        "heat_pump_type": "luft",
        "persons": 2,
        "latitude": 48.2,
        "longitude": 11.0,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
    }
    weekly = weekly_electric_kwh(**params)
    profile = thermal_on_off_hourly_profile(
        weekly,
        nominal_power_kw=3.0,
        hours_per_year=8760,
    )
    hours_per_week = 8760 // 52
    for week_idx, week_kwh in enumerate(weekly):
        start = week_idx * hours_per_week
        end = start + hours_per_week
        assert sum(profile[start:end]) == pytest.approx(week_kwh, rel=1e-3)


def test_thermal_hourly_overlay_maps_slots():
    profile = {
        "consumers": [
            {
                "id": "wp",
                "type": "thermal_annual",
                "nominal_power_kw": 3.0,
                "living_area_m2": 100.0,
                "building_class": 3,
                "heat_pump_type": "luft",
                "persons": 2,
                "latitude": 48.2,
                "longitude": 11.0,
            }
        ]
    }
    slots = [datetime(2023, 1, 15, h, 0) for h in range(24)]
    overlay = thermal_hourly_overlay(profile, slots)
    assert len(overlay) == 24
    assert any(kw > 0 for kw in overlay)
    assert all(kw == pytest.approx(0.0) or kw == pytest.approx(3.0) for kw in overlay)
