"""Tests for Hausprofil consumer passthrough (EHAL bindings live on EHAL-Com)."""
from __future__ import annotations

from ui.house_config_profile_form import (
    _live_markers_enabled,
    _merge_passthrough_consumer_fields,
    _preserved_appliance_power_source,
)


def test_live_markers_enabled_follows_ui_modes(monkeypatch) -> None:
    monkeypatch.setattr(
        "ui.mode_selector.get_enabled_ui_mode_keys",
        lambda: ["sunset2sunset", "scenario_explorer"],
    )
    assert _live_markers_enabled() is False
    monkeypatch.setattr(
        "ui.mode_selector.get_enabled_ui_mode_keys",
        lambda: ["sunset2sunset", "live_environment"],
    )
    assert _live_markers_enabled() is True


def test_preserved_appliance_power_source() -> None:
    assert (
        _preserved_appliance_power_source(
            {"appliance_recommendation": {"power_source": "loxone"}}
        )
        == "loxone"
    )
    assert (
        _preserved_appliance_power_source(
            {"id": "x", "ehal_bindings": {"flex.x.sens_power_act": "P_act"}}
        )
        == "loxone"
    )
    assert (
        _preserved_appliance_power_source(
            {"ehal_bindings": {"flex.power_name": "P_act"}}
        )
        == "loxone"
    )
    assert (
        _preserved_appliance_power_source(
            {"loxone_inputs": {"power_name": "P_act"}}
        )
        == "loxone"
    )
    assert _preserved_appliance_power_source({}) == "manual"


def test_omit_marker_keys_preserves_via_passthrough() -> None:
    original = {
        "id": "wp",
        "label": "WP",
        "type": "thermal_annual",
        "loxone_inputs": {"power_name": "Ernie_WP_P_act"},
        "loxone_outputs": {"enable_name": "Ernie_WP_Freigabe"},
        "thermal_control": {"loxone": {"heating_active_name": "heat"}},
        "filter_schedule": {"enabled": True, "config_fallback": {"native_start_hour": 10}},
        "ehal_bindings": {"flex.power_name": "Ernie_WP_P_act"},
    }
    edited = {
        "id": "wp",
        "label": "WP",
        "type": "thermal_annual",
        "living_area_m2": 120.0,
    }
    merged = _merge_passthrough_consumer_fields(original, edited)
    assert merged["loxone_inputs"]["power_name"] == "Ernie_WP_P_act"
    assert merged["loxone_outputs"]["enable_name"] == "Ernie_WP_Freigabe"
    assert merged["thermal_control"]["loxone"]["heating_active_name"] == "heat"
    assert merged["filter_schedule"]["enabled"] is True
    assert merged["ehal_bindings"]["flex.power_name"] == "Ernie_WP_P_act"


def test_omit_charging_loxone_preserves_via_passthrough() -> None:
    original = {
        "id": "ev",
        "type": "ev",
        "loxone_inputs": {"power_name": "P"},
        "charging_schedule": {
            "target_soc_percent": 100.0,
            "loxone": {"plugged_in_name": "Da"},
        },
        "ehal_bindings": {"sens_evcs_connected": "Da"},
    }
    edited = {
        "id": "ev",
        "type": "ev",
        "charging_schedule": {"target_soc_percent": 90.0},
    }
    merged = _merge_passthrough_consumer_fields(original, edited)
    assert merged["charging_schedule"]["loxone"]["plugged_in_name"] == "Da"
    assert merged["loxone_inputs"]["power_name"] == "P"
    assert merged["charging_schedule"]["target_soc_percent"] == 90.0
    assert merged["ehal_bindings"]["sens_evcs_connected"] == "Da"
