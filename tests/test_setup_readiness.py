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
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_COMPONENTS_PATH",
        str(config_dir / "components.json"),
    )
    return config_dir


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _minimal_config():
    return {
        "flexible_consumers": [],
    }


def _empty_components():
    return {"batteries": [], "pv_systems": []}


def test_needs_planning_onboarding_after_minimal_bootstrap(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", _minimal_config())
    _write(config_dir / "components.json", _empty_components())

    assert setup_readiness.needs_planning_onboarding() is True


def test_prod_config_skips_onboarding(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            "flexible_consumers": [{"id": "swimspa"}],
        },
    )
    _write(
        config_dir / "components.json",
        {"batteries": [{"id": "bat"}], "pv_systems": []},
    )

    assert setup_readiness.needs_planning_onboarding() is False
    assert setup_readiness.is_planning_ready() is True
    assert setup_readiness.is_setup_navigation_restricted() is False


def test_missing_house_config_items_lists_gaps(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", _minimal_config())
    _write(
        config_dir / "components.json",
        {"batteries": [{"id": "bat", "battery_capacity_kwh": 5.0}], "pv_systems": []},
    )
    _write(config_dir / "house_profiles.json", {"profiles": []})

    missing = setup_readiness.missing_house_config_items()

    assert missing == ["Hausprofil anlegen (Hauskonfigurator → Hausprofil)"]


def test_missing_house_config_items_lists_battery_gap(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", _minimal_config())
    _write(config_dir / "components.json", _empty_components())
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
    _write(config_dir / "components.json", _empty_components())
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


def test_planning_ready_unlocks_scenario_explorer(tmp_path, monkeypatch):
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
        {"batteries": [{"id": "bat", "battery_capacity_kwh": 5.0}], "pv_systems": []},
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


def test_loxone_sidebar_deferred_after_planning_unlock(tmp_path, monkeypatch):
    """Greenfield: Szenario-Explorer frei, aber Loxone-.env noch Platzhalter."""
    from runtime_store import dotenv_io
    from runtime_store.dotenv_io import format_loxone_dotenv
    from runtime_store.dotenv_loader import load_app_dotenv

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
        {"batteries": [{"id": "bat", "battery_capacity_kwh": 5.0}], "pv_systems": []},
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
    dotenv_path = config_dir / ".env"
    dotenv_path.write_text(
        'LOXONE_USER="name-des-benutzers-in-der-loxone"\n'
        'LOXONE_PASS="Passwort-des-benutzers-in-der-loxone"\n'
        "LOXONE_IP=192.168.178.1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_DOTENV_PATH", str(dotenv_path))
    monkeypatch.delenv("ENERGY_OPTIMIZER_OFFLINE", raising=False)
    for key in ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS"):
        monkeypatch.delenv(key, raising=False)
    load_app_dotenv(override=True)

    assert setup_readiness.is_planning_ready() is True
    assert setup_readiness.needs_planning_onboarding() is True
    from runtime_store import env_vars

    assert env_vars.is_effective_offline() is False
    assert dotenv_io.loxone_credentials_configured() is False
    assert dotenv_io.loxone_setup_deferred() is True
    assert dotenv_io.needs_loxone_setup() is False

    dotenv_path.write_text(
        format_loxone_dotenv("192.168.178.99", "greenfield", "dev-only"),
        encoding="utf-8",
    )
    load_app_dotenv(override=True)
    monkeypatch.setenv("LOXONE_IP", "192.168.178.99")
    monkeypatch.setenv("LOXONE_USER", "greenfield")
    monkeypatch.setenv("LOXONE_PASS", "dev-only")

    assert dotenv_io.loxone_credentials_configured() is True
    assert dotenv_io.loxone_setup_deferred() is False


def test_needs_planning_onboarding_true_for_empty_flex_list():
    assert setup_readiness.needs_planning_onboarding_from_raw({"flexible_consumers": []}) is True
    assert setup_readiness.needs_planning_onboarding_from_raw({}) is True
    assert (
        setup_readiness.needs_planning_onboarding_from_raw(
            {"flexible_consumers": [{"id": "swimspa"}]}
        )
        is False
    )


def test_needs_planning_onboarding_false_for_migrated_profile_loxone():
    profiles_doc = {
        "profiles": [
            {
                "id": "example_efh",
                "consumers": [
                    {
                        "id": "ev",
                        "loxone_inputs": {"power_name": "Ernie_EAuto_P_act"},
                    }
                ],
            }
        ]
    }
    assert (
        setup_readiness.needs_planning_onboarding_from_raw(
            {"flexible_consumers": [], "live_scenario_id": "live"},
            profiles_doc=profiles_doc,
        )
        is False
    )


def test_betrieb_unlocked_after_live_config(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(
        config_dir / "config.json",
        {
            "flexible_consumers": [{"id": "swimspa"}],
        },
    )
    _write(
        config_dir / "components.json",
        {"batteries": [{"id": "bat"}], "pv_systems": []},
    )

    assert setup_readiness.is_betrieb_unlocked() is True


def test_scenario_editor_unlocked_after_house_config(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    _write(config_dir / "config.json", _minimal_config())
    _write(
        config_dir / "components.json",
        {"batteries": [{"id": "bat", "battery_capacity_kwh": 5.0}], "pv_systems": []},
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
