"""Tests für Hauskonfigurator-Entitäten, Tarife und Szenario-Auflösung (Version 1.24)."""
from __future__ import annotations

import config
from data.consumption_profiles import build_hourly_kw_profile
from house_config.baseload import compute_baseload_kwh
from house_config.entity_resolution import (
    batteries_by_id,
    resolve_battery_into_settings,
    resolve_pv_into_settings,
)
from house_config.profiles_store import load_house_profiles_document
from house_config.tariffs_store import load_tariffs_document


def test_batteries_by_id_from_fixture():
    batteries = batteries_by_id(config.CONFIG._raw_config)
    assert "test_battery" in batteries
    assert batteries["test_battery"]["battery_capacity_kwh"] == 8.0


def test_resolve_battery_into_settings():
    batteries = batteries_by_id(config.CONFIG._raw_config)
    resolved = resolve_battery_into_settings({"battery_id": "test_battery"}, batteries)
    assert resolved["battery_capacity_kwh"] == 8.0
    assert "battery_id" not in resolved


def test_resolve_pv_into_settings():
    from house_config.entity_resolution import pv_systems_by_id

    pv_map = pv_systems_by_id(config.CONFIG._raw_config)
    resolved = resolve_pv_into_settings({"pv_system_id": "test_pv"}, pv_map)
    assert resolved["pv_kwp"] == 6.0


def test_scenario_entity_resolution():
    scenarios = config.get_backtesting_scenarios()
    assert "entity_test" in scenarios
    entity = scenarios["entity_test"]
    assert entity["battery_capacity_kwh"] == 8.0
    assert entity["pv_kwp"] == 6.0
    assert entity["feed_in_mode"] == "fixed"
    assert entity.get("_monthly_fixed_tariffs") is not None
    assert entity.get("_house_profile") is not None


def test_baseload_minimum_fraction():
    result = compute_baseload_kwh(4000, [{"annual_kwh": 3900, "type": "generic"}])
    assert result["baseload_kwh"] >= 200.0


def test_house_profile_thermal_annual():
    path = config.HOUSE_PROFILES_JSON_PATH
    doc = load_house_profiles_document(path)
    profile = doc["profiles"]["test_home"]
    assert profile["baseload_kwh"] >= profile["baseload_min_kwh"]
    hourly = build_hourly_kw_profile(profile, hours=168)
    assert len(hourly) == 168
    assert sum(hourly) > 0


def test_tariffs_document():
    doc = load_tariffs_document(config.TARIFFS_JSON_PATH)
    assert "monthly_test" in doc["export_tariffs"]
