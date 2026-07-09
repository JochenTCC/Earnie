# tests/test_setup_readiness.py
"""Tests für Greenfield-Onboarding und UI-Freischaltung."""
from __future__ import annotations

import json

import pytest

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


def test_missing_planning_items_lists_all_gaps(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", _minimal_config())
    _write(config_dir / "house_profiles.json", {"profiles": []})
    _write(config_dir / "tariffs.json", {"import_tariffs": [], "export_tariffs": []})

    missing = setup_readiness.missing_planning_setup_items()

    assert "PV-Anlage (Hauskonfigurator → PV-Anlage)" in missing
    assert "Batterie (Hauskonfigurator → Batterie)" in missing
    assert "Hausprofil mit thermischem Verbraucher (Hauskonfigurator → Hausprofil)" in missing
    assert "Bezugstarif wählen (Hauskonfigurator → Tarife)" in missing
    assert "Einspeisetarif wählen (Hauskonfigurator → Tarife)" in missing


def test_planning_ready_unlocks_backtesting(tmp_path, monkeypatch):
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
                    "consumers": [{"id": "wp", "type": "thermal_annual"}],
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

    assert setup_readiness.is_planning_ready() is True
    assert setup_readiness.is_setup_navigation_restricted() is False


def test_scenario_editor_locked_during_onboarding(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", _minimal_config())

    assert setup_readiness.is_scenario_editor_unlocked() is False
