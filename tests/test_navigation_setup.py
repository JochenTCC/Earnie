# tests/test_navigation_setup.py
"""Tests für eingeschränkte Navigation nach Minimal-Bootstrap."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID
from ui.navigation import build_page_specs


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
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_COMPONENTS_PATH",
        str(config_dir / "components.json"),
    )
    return config_dir


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_live_scenario(config_dir: Path, settings: dict) -> None:
    _write(
        config_dir / "backtesting_scenarios.json",
        {
            "scenarios": [
                {
                    "id": DEFAULT_LIVE_SCENARIO_ID,
                    "label": "Live",
                    "settings": settings,
                }
            ]
        },
    )


def test_restricted_navigation_shows_only_setup_pages(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", {"flexible_consumers": []})
    _write(config_dir / "components.json", {"batteries": [], "pv_systems": []})
    _write(config_dir / "house_profiles.json", {"profiles": []})
    _write(
        config_dir / "tariffs.json",
        {"import_tariffs": [], "export_tariffs": []},
    )
    _write_live_scenario(
        config_dir,
        {
            "battery_id": "",
            "pv_system_id": "",
            "import_tariff_id": "",
            "export_tariff_id": "",
            "house_profile_id": "",
        },
    )

    specs = build_page_specs(["scenario_exploration"])
    titles = [spec.title for spec in specs]

    assert titles == ["Hauskonfigurator", "Live-Konfiguration", "Loxone-Kommunikation"]


def test_scenario_editor_after_house_config_ready(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            "live_scenario_id": DEFAULT_LIVE_SCENARIO_ID,
            "flexible_consumers": [],
        },
    )
    _write(
        config_dir / "components.json",
        {
            "batteries": [{"id": "bat", "battery_capacity_kwh": 5.0}],
            "pv_systems": [{"id": "pv"}],
        },
    )
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
    _write_live_scenario(
        config_dir,
        {
            "battery_id": "",
            "pv_system_id": "",
            "import_tariff_id": "",
            "export_tariff_id": "",
            "house_profile_id": "efh",
        },
    )

    specs = build_page_specs(["scenario_exploration"])
    titles = [spec.title for spec in specs]

    assert titles == ["Hauskonfigurator", "Szenarieneditor", "Live-Konfiguration", "Loxone-Kommunikation"]
    assert "Scenario-Exploration" not in titles


def test_scenario_exploration_visible_when_planning_ready(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            "live_scenario_id": DEFAULT_LIVE_SCENARIO_ID,
            "flexible_consumers": [],
        },
    )
    _write(
        config_dir / "components.json",
        {
            "batteries": [{"id": "bat"}],
            "pv_systems": [{"id": "pv"}],
        },
    )
    _write(
        config_dir / "house_profiles.json",
        {
            "profiles": [
                {
                    "id": "efh",
                    "annual_kwh": 4000,
                    "latitude": 48.2,
                    "longitude": 11.0,
                    "consumers": [{"id": "wp", "type": "thermal_annual", "living_area_m2": 100}],
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
    _write_live_scenario(
        config_dir,
        {
            "battery_id": "bat",
            "pv_system_id": "pv",
            "house_profile_id": "efh",
            "import_tariff_id": "imp",
            "export_tariff_id": "exp",
        },
    )

    specs = build_page_specs(["scenario_exploration"])
    titles = [spec.title for spec in specs]

    assert "Scenario-Exploration" in titles
