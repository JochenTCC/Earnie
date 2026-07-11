# tests/test_setup_readiness.py
"""Tests für Greenfield-Onboarding und UI-Freischaltung."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID
from ui import setup_readiness


def _bind_config_paths(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_TARIFFS_PATH", str(config_dir / "tariffs.json"))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    return config_dir


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _minimal_config():
    return {
        "batteries": [],
        "pv_systems": [],
        "flexible_consumers": [],
    }


def test_needs_planning_onboarding_after_minimal_bootstrap(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", _minimal_config())

    assert setup_readiness.needs_planning_onboarding() is True


def test_prod_config_skips_onboarding(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            "batteries": [{"id": "bat"}],
            "pv_systems": [],
            "flexible_consumers": [{"id": "swimspa"}],
        },
    )

    assert setup_readiness.needs_planning_onboarding() is False
    assert setup_readiness.is_planning_ready() is True
    assert setup_readiness.is_setup_navigation_restricted() is False


def test_missing_house_config_items_lists_gaps(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            **_minimal_config(),
            "batteries": [{"id": "bat", "battery_capacity_kwh": 5.0}],
        },
    )
    _write(config_dir / "house_profiles.json", {"profiles": []})

    missing = setup_readiness.missing_house_config_items()

    assert missing == ["Hausprofil anlegen (Hauskonfigurator → Hausprofil)"]


def test_missing_house_config_items_lists_battery_gap(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", _minimal_config())
    _write(
        config_dir / "house_profiles.json",
        {
            "profiles": [
                {
                    "id": "efh",
                    "latitude": 48.2,
                    "longitude": 11.0,
                    "consumers": [{"id": "wp", "type": "thermal_annual"}],
                }
            ]
        },
    )

    missing = setup_readiness.missing_house_config_items()

    assert missing == ["Batterie anlegen (Hauskonfigurator → Batterien)"]


def test_missing_runtime_scenario_items_lists_gaps(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", _minimal_config())
    _write(
        config_dir / "house_profiles.json",
        {
            "profiles": [
                {
                    "id": "efh",
                    "latitude": 48.2,
                    "longitude": 11.0,
                    "consumers": [{"id": "wp", "type": "thermal_annual"}],
                }
            ]
        },
    )
    _write(config_dir / "tariffs.json", {"import_tariffs": [], "export_tariffs": []})
    _write(
        config_dir / "backtesting_scenarios.json",
        {
            "scenarios": [
                {
                    "id": DEFAULT_LIVE_SCENARIO_ID,
                    "label": "Live",
                    "settings": {
                        "battery_id": "",
                        "import_tariff_id": "",
                        "export_tariff_id": "",
                        "house_profile_id": "",
                    },
                }
            ]
        },
    )

    missing = setup_readiness.missing_runtime_scenario_items()

    assert "Batterie anlegen (Hauskonfigurator → Batterien)" not in missing
    assert "Bezugstarif wählen (Echtzeit-Umgebung)" in missing


def test_planning_ready_unlocks_scenario_exploration(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            "live_scenario_id": DEFAULT_LIVE_SCENARIO_ID,
            "batteries": [{"id": "bat", "battery_capacity_kwh": 5.0}],
            "pv_systems": [],
            "flexible_consumers": [],
        },
    )
    _write(
        config_dir / "house_profiles.json",
        {
            "profiles": [
                {
                    "id": "efh",
                    "label": "EFH",
                    "annual_kwh": 4000.0,
                    "latitude": 48.2,
                    "longitude": 11.0,
                    "consumers": [],
                }
            ]
        },
    )
    _write(
        config_dir / "tariffs.json",
        {
            "import_tariffs": [{"id": "imp", "label": "Import", "type": "awattar"}],
            "export_tariffs": [
                {"id": "exp", "label": "Export", "type": "fixed", "k_push_cent": 3.7}
            ],
        },
    )
    _write(
        config_dir / "backtesting_scenarios.json",
        {
            "scenarios": [
                {
                    "id": DEFAULT_LIVE_SCENARIO_ID,
                    "label": "Live",
                    "settings": {
                        "battery_id": "bat",
                        "pv_system_id": "",
                        "house_profile_id": "efh",
                        "import_tariff_id": "imp",
                        "export_tariff_id": "exp",
                    },
                }
            ]
        },
    )

    assert setup_readiness.is_house_config_ready() is True
    assert setup_readiness.is_runtime_scenario_ready() is True
    assert setup_readiness.is_planning_ready() is True
    assert setup_readiness.is_setup_navigation_restricted() is False
    assert setup_readiness.is_betrieb_unlocked() is False


def test_betrieb_unlocked_after_live_config(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            "batteries": [{"id": "bat"}],
            "pv_systems": [],
            "flexible_consumers": [{"id": "swimspa"}],
        },
    )

    assert setup_readiness.is_betrieb_unlocked() is True


def test_scenario_editor_unlocked_after_house_config(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            **_minimal_config(),
            "batteries": [{"id": "bat", "battery_capacity_kwh": 5.0}],
        },
    )
    _write(
        config_dir / "house_profiles.json",
        {
            "profiles": [
                {
                    "id": "efh",
                    "label": "EFH",
                    "annual_kwh": 4000.0,
                    "latitude": 48.2,
                    "longitude": 11.0,
                    "consumers": [],
                }
            ]
        },
    )

    assert setup_readiness.is_scenario_editor_unlocked() is True
    assert setup_readiness.is_planning_ready() is False
