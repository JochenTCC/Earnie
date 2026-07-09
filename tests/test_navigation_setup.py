# tests/test_navigation_setup.py
"""Tests für eingeschränkte Navigation nach Minimal-Bootstrap."""
from __future__ import annotations

import json

import pytest

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
    return config_dir


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_restricted_navigation_shows_only_setup_pages(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {"batteries": [], "pv_systems": [], "flexible_consumers": []},
    )
    _write(config_dir / "house_profiles.json", {"profiles": []})
    _write(
        config_dir / "tariffs.json",
        {"import_tariffs": [], "export_tariffs": []},
    )

    specs = build_page_specs(["backtesting"])
    titles = [spec.title for spec in specs]

    assert titles == ["Hauskonfigurator", "Konfiguration"]


def test_backtesting_hidden_until_planning_ready(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            "batteries": [{"id": "bat"}],
            "pv_systems": [{"id": "pv"}],
            "flexible_consumers": [],
            "runtime_settings": {
                "import_tariff_id": "imp",
                "export_tariff_id": "exp",
            },
        },
    )
    _write(
        config_dir / "house_profiles.json",
        {
            "profiles": [
                {
                    "id": "efh",
                    "annual_kwh": 4000,
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

    specs = build_page_specs(["backtesting"])
    titles = [spec.title for spec in specs]

    assert "Backtesting" in titles
    assert "Szenarieneditor" not in titles
