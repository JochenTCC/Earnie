# tests/test_cons_data_calendar_alignment.py
"""Kalender-Ausrichtung cons_data-Synthese vs. Backtesting-Overlay."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from data.cons_data_house_profile import build_synthetic_dataframe_from_house_profile
from data.modeled_climate import ModeledClimateContext
from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock
from data.profile_manager import _cons_data_to_profile_dataframe
from house_config.planning_flex_bridge import (
    house_profile_baseload_overlay,
    thermal_hourly_overlay,
)
from simulation.baseload_validation import resolve_hourly_baseload_kw
from simulation.engine import HistoricalDataCache, window_slot_datetimes


def _greenfield_profile() -> dict:
    path = Path("greenfield/config/house_profiles.json")
    if not path.is_file():
        pytest.skip("greenfield house_profiles.json not available")
    profiles = json.loads(path.read_text(encoding="utf-8"))["profiles"]
    return next(item for item in profiles if item["id"] == "mein_haushalt")


def _mock_open_meteo_climate(monkeypatch) -> None:
    install_open_meteo_climate_mock(monkeypatch)


def test_synthetic_haus_kw_matches_thermal_overlay_for_jan_14(monkeypatch):
    _mock_open_meteo_climate(monkeypatch)
    profile = _greenfield_profile()
    climate = ModeledClimateContext.for_house_profile(profile, kwp=5.0)
    df = build_synthetic_dataframe_from_house_profile(
        profile,
        start=date(2025, 1, 14),
        end=date(2025, 1, 14),
        kwp=5.0,
        source="synthetic",
        climate=climate,
    )
    anchor = datetime(2025, 1, 15, 0, 0)
    slots = window_slot_datetimes(anchor)
    thermal = thermal_hourly_overlay(profile, slots, climate=climate)
    assert float(df["haus_kw"].sum()) == pytest.approx(sum(thermal), rel=1e-6)
    assert float(df["haus_kw"].sum()) > 0.0


def test_baseload_overlay_skipped_when_haus_in_cons_data(monkeypatch):
    _mock_open_meteo_climate(monkeypatch)
    consumer_ids = ["haus", "ev", "rest"]
    monkeypatch.setattr(
        "data.cons_data_house_profile.expected_cons_data_consumer_ids",
        lambda: consumer_ids,
    )
    profile = _greenfield_profile()
    climate = ModeledClimateContext.for_house_profile(profile, kwp=5.0)
    df = build_synthetic_dataframe_from_house_profile(
        profile,
        start=date(2025, 1, 14),
        end=date(2025, 1, 14),
        kwp=5.0,
        source="synthetic",
        climate=climate,
    )
    anchor = datetime(2025, 1, 15, 0, 0)
    slots = window_slot_datetimes(anchor)
    cache = HistoricalDataCache()
    cache._consumption_df = _cons_data_to_profile_dataframe(df)
    cache._pv_series = df["pv_kw"]
    _, hist_totals, total_load, hourly_flex = cache.get_window_consumption(
        slots,
        flex_consumer_ids=["ev", "rest"],
    )
    _, all_consumer_totals, _, _ = cache.get_window_consumption(slots)
    overlay = house_profile_baseload_overlay(
        profile,
        slots,
        historical_totals=all_consumer_totals,
        climate=climate,
    )
    assert sum(overlay) == pytest.approx(0.0, abs=1e-6)
    _, baseload_sum = resolve_hourly_baseload_kw(total_load, hourly_flex)
    baseload_with_overlay = baseload_sum + sum(overlay)
    optimized_total = baseload_with_overlay + sum(hist_totals.values())
    assert round(sum(total_load), 3) == pytest.approx(optimized_total, rel=1e-6)


def test_baseload_overlay_skipped_when_haus_column_zero_in_cons_data(monkeypatch):
    """Kein Thermik-Overlay wenn haus_kw-Spalte existiert aber am Tag 0 kWh (Heiz-Aus)."""
    _mock_open_meteo_climate(monkeypatch)
    consumer_ids = ["haus", "ev", "rest"]
    monkeypatch.setattr(
        "data.cons_data_house_profile.expected_cons_data_consumer_ids",
        lambda: consumer_ids,
    )
    profile = _greenfield_profile()
    climate = ModeledClimateContext.for_house_profile(profile, kwp=5.0)
    df = build_synthetic_dataframe_from_house_profile(
        profile,
        start=date(2025, 1, 14),
        end=date(2025, 1, 14),
        kwp=5.0,
        source="synthetic",
        climate=climate,
    )
    df["haus_kw"] = 0.0
    df["total_kw"] = (
        df["baseload_kw"].astype(float)
        + df["ev_kw"].astype(float)
        + df["rest_kw"].astype(float)
    ).round(3)

    anchor = datetime(2025, 1, 15, 0, 0)
    slots = window_slot_datetimes(anchor)
    cache = HistoricalDataCache()
    cache._consumption_df = _cons_data_to_profile_dataframe(df)
    cache._pv_series = df["pv_kw"]
    _, hist_totals, total_load, hourly_flex = cache.get_window_consumption(
        slots,
        flex_consumer_ids=["ev", "rest"],
    )
    _, all_consumer_totals, _, _ = cache.get_window_consumption(slots)
    cons_data_ids = cache.cons_data_consumer_ids_present()
    overlay = house_profile_baseload_overlay(
        profile,
        slots,
        historical_totals=all_consumer_totals,
        cons_data_consumer_ids=cons_data_ids,
        climate=climate,
    )
    assert "haus" in cons_data_ids
    assert float(all_consumer_totals.get("haus", -1.0)) == 0.0
    assert sum(overlay) == pytest.approx(0.0, abs=1e-6)
    _, baseload_sum = resolve_hourly_baseload_kw(total_load, hourly_flex)
    optimized_total = baseload_sum + sum(overlay) + sum(hist_totals.values())
    assert round(sum(total_load), 3) == pytest.approx(optimized_total, rel=1e-6)
