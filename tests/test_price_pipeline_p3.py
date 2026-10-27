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
from data.heating_need import (
    daily_electric_kwh,
    thermal_daily_pwm_hourly_profile,
    thermal_on_off_hourly_profile,
    weekly_electric_kwh,
)
from data.market_prices import resolve_market_slots
from house_config.planning_flex_bridge import thermal_hourly_overlay

VIENNA = ZoneInfo("Europe/Vienna")

_AWATTAR_SURCHARGES = {
    "settlement_fee_cent_kwh": 1.5,
    "markup_percent": 3.0,
    "prices_include_vat": False,
    "vat_percent": 20.0,
}


def _write_pack(tmp_path, *, grid_fee_cent: float | None = None) -> dict[str, str]:
    """Tariff files in Edibert format: a quarter-hour spot tariff with aWATTar surcharges and a
    fixed import tariff; optionally a flat user grid area."""
    import json

    from house_config.edibert_tariffs import flat_user_grid_area

    tariffs = {
        "tariff_format": 1,
        "import_tariffs": [
            {"id": "spot_qh", "label": "Spot", "type": "spot_hourly", "land": "AT",
             "supplier_id": "awattar_at", **_AWATTAR_SURCHARGES},
            {"id": "fixed_imp", "label": "Fix", "type": "fixed_cent", "land": "AT",
             "supplier_id": "fix", "fix_cent_kwh": 37.0, "prices_include_vat": True,
             "vat_percent": 0.0},
        ],
        "export_tariffs": [],
    }
    (tmp_path / "tariffs.json").write_text(json.dumps(tariffs), encoding="utf-8")
    (tmp_path / "grid_fees.json").write_text(
        json.dumps({"tariff_format": 1, "rule_sets": {}, "areas": []}), encoding="utf-8"
    )
    if grid_fee_cent is not None:
        area = flat_user_grid_area("user_home", grid_fee_cent, label="Home", land="AT")
        (tmp_path / "user_grid_fees.json").write_text(
            json.dumps({"tariff_format": 1, "rule_sets": {}, "areas": [area]}), encoding="utf-8"
        )
    return {"tariffs": str(tmp_path / "tariffs.json"), "grid": str(tmp_path / "grid_fees.json")}


def _resolved(tmp_path, import_id: str, *, grid_fee_cent: float | None = None) -> dict:
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, pricing_reference

    paths = _write_pack(tmp_path, grid_fee_cent=grid_fee_cent)
    profile: dict = {"land": "AT"}
    if grid_fee_cent is not None:
        profile["netznutzung"] = {"area_id": "user_home", "quarter_hour_meter": True}
    return {
        EDIBERT_PRICING_KEY: pricing_reference(
            tariffs_path=paths["tariffs"], grid_fees_path=paths["grid"],
            import_tariff_id=import_id, export_tariff_id=None,
            timezone_name="Europe/Vienna", profile=profile,
        )
    }


@pytest.mark.parametrize("import_id", ["spot_qh", "fixed_imp"])
def test_live_and_backtesting_import_prices_match(tmp_path, import_id):
    resolved = _resolved(tmp_path, import_id)
    slots = [datetime(2025, 6, 10, h, 0) for h in range(6)]
    epex = [4.2, 5.1, 6.0, 7.3, 8.0, 3.9]
    kwargs = pricing_kwargs_from_resolved(resolved)

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


def test_enrich_slots_import_prices_matches_matrix(tmp_path):
    kwargs = pricing_kwargs_from_resolved(_resolved(tmp_path, "spot_qh"))
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


def test_se_chart_strompreis_includes_netznutzung(tmp_path):
    """SE Chart 1 Preis is k_act; k_act already includes house-profile NNE AP."""
    from optimizer.sim_chart_rows import _chart_price_fields

    slots = [datetime(2025, 6, 10, 12, 0)]
    epex = [10.0]
    with_nne = import_brutto_cent_for_slots(
        epex, slots, **pricing_kwargs_from_resolved(_resolved(tmp_path, "spot_qh", grid_fee_cent=5.0))
    )[0]
    other = tmp_path / "plain"
    other.mkdir()
    without_nne = import_brutto_cent_for_slots(
        epex, slots, **pricing_kwargs_from_resolved(_resolved(other, "spot_qh"))
    )[0]
    fields = _chart_price_fields({"k_act": with_nne, "price_source": "day_ahead"})
    assert fields["Strompreis (Cent/kWh)"] == pytest.approx(with_nne)
    assert with_nne == pytest.approx(without_nne + 5.0 * 1.2)


def test_monday_of_week_snaps_to_monday():
    wednesday = pd.Timestamp("2025-07-09")
    monday = _monday_of_week(wednesday)
    assert monday.dayofweek == 0
    assert monday.date().isoformat() == "2025-07-07"


def test_resolve_simulation_window_month_aligned_from_cons_data(monkeypatch):
    from datetime import date

    monkeypatch.setattr(
        "data.profile_manager.get_cons_data_date_bounds",
        lambda: (date(2025, 1, 10), date(2026, 6, 25)),
    )
    start, end = resolve_simulation_window("last_12_months")
    assert end.normalize() == pd.Timestamp("2026-05-31")
    assert start.normalize() == pd.Timestamp("2025-06-01")


def test_resolve_simulation_window_complete_month_end(monkeypatch):
    from datetime import date

    monkeypatch.setattr(
        "data.profile_manager.get_cons_data_date_bounds",
        lambda: (date(2025, 7, 1), date(2026, 6, 30)),
    )
    start, end = resolve_simulation_window()
    assert end.normalize() == pd.Timestamp("2026-06-30")
    assert start.normalize() == pd.Timestamp("2025-07-01")


def test_resolve_simulation_window_empty_cons_data(monkeypatch):
    monkeypatch.setattr(
        "data.profile_manager.get_cons_data_date_bounds",
        lambda: (None, None),
    )
    with pytest.raises(ValueError, match="cons_data"):
        resolve_simulation_window()


def test_thermal_daily_pwm_uses_nominal_or_zero():
    daily = [2.0] * 7
    nominal = 2.0
    profile = thermal_daily_pwm_hourly_profile(
        daily,
        nominal_power_kw=nominal,
        hours_per_year=168,
    )
    assert len(profile) == 168
    for kw in profile:
        assert kw == pytest.approx(0.0) or kw == pytest.approx(nominal)
    assert sum(profile[:24]) == pytest.approx(2.0, rel=1e-3)


def test_thermal_daily_pwm_preserves_daily_kwh():
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
    daily = daily_electric_kwh(**params)
    profile = thermal_daily_pwm_hourly_profile(
        daily,
        nominal_power_kw=3.0,
        hours_per_year=8760,
    )
    for day_idx, day_kwh in enumerate(daily):
        start = day_idx * 24
        end = start + 24
        assert sum(profile[start:end]) == pytest.approx(day_kwh, rel=1e-3)


def test_thermal_daily_pwm_pulse_lengths_within_one_to_four_hours():
    daily = [12.0, 4.0, 1.5]
    profile = thermal_daily_pwm_hourly_profile(
        daily,
        nominal_power_kw=3.0,
        hours_per_year=72,
    )
    for day_offset in range(3):
        day_slice = profile[day_offset * 24 : (day_offset + 1) * 24]
        on_runs: list[int] = []
        run = 0
        for kw in day_slice:
            if kw > 0.0:
                run += 1
            elif run:
                on_runs.append(run)
                run = 0
        if run:
            on_runs.append(run)
        for run_hours in on_runs:
            assert 1 <= run_hours <= 4


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


def test_thermal_hourly_overlay_maps_slots(monkeypatch):
    # Keep offline: CI sonarcloud hit ReadTimeout on archive-api.open-meteo.com.
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
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
    for kw in overlay:
        assert kw == pytest.approx(0.0) or (0.0 < kw <= 3.0 + 1e-6)
