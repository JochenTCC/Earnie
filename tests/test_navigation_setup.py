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
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv(
        "EARNIE_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.setenv("EARNIE_TARIFFS_PATH", str(config_dir / "tariffs.json"))
    monkeypatch.setenv(
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    monkeypatch.setenv(
        "EARNIE_COMPONENTS_PATH",
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
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.delenv("LOXONE_USER", raising=False)
    monkeypatch.delenv("LOXONE_PASS", raising=False)
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
            "pv_system_ids": [],
            "import_tariff_id": "",
            "export_tariff_id": "",
            "house_profile_id": "",
        },
    )

    specs = build_page_specs(["scenario_explorer"])
    titles = [spec.title for spec in specs]

    assert titles == [
        "Hauskonfigurator",
        "Smarthome-Backend",
    ]


def test_restricted_navigation_shows_daemon_pages_once_sb_configured(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("LOXONE_IP", "192.168.178.20")
    monkeypatch.setenv("LOXONE_USER", "earnie")
    monkeypatch.setenv("LOXONE_PASS", "secret")
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
            "pv_system_ids": [],
            "import_tariff_id": "",
            "export_tariff_id": "",
            "house_profile_id": "",
        },
    )

    specs = build_page_specs(["scenario_explorer"])
    titles = [spec.title for spec in specs]

    assert titles == [
        "Hauskonfigurator",
        "Smarthome-Backend",
        "Optimierer-Dienst",
        "EHAL-Com",
    ]


def test_general_nav_hides_daemon_pages_for_mature_config_without_backend(
    tmp_path, monkeypatch
):
    """Mature config (never restricted) that has never had a backend configured
    must not leak Optimierer-Dienst/EHAL-Com into live_environment nav either.

    The pre-nav blocking gate (loxone_setup_deferred) intentionally stays
    deferred for exactly this state (mature config, no backend ever
    configured) — see runtime_store/dotenv_io.py::loxone_setup_deferred and
    tests/test_dotenv_io.py::test_require_loxone_credentials_for_prod_without_onboarding.
    Nav-level gating via is_sb_configured() is what actually closes this.
    """
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.delenv("LOXONE_USER", raising=False)
    monkeypatch.delenv("LOXONE_PASS", raising=False)
    _write(
        config_dir / "config.json",
        {"flexible_consumers": [{"id": "swimspa", "name": "SwimSpa"}]},
    )
    _write(config_dir / "components.json", {"batteries": [], "pv_systems": []})
    _write(config_dir / "house_profiles.json", {"profiles": []})
    _write(
        config_dir / "tariffs.json",
        {"import_tariffs": [], "export_tariffs": []},
    )

    from ui.setup_readiness import is_setup_navigation_restricted, needs_planning_onboarding

    assert needs_planning_onboarding() is False
    assert is_setup_navigation_restricted() is False

    specs = build_page_specs(["live_environment"])
    titles = [spec.title for spec in specs]

    assert "Smarthome-Backend" in titles
    assert "Optimierer-Dienst" not in titles
    assert "EHAL-Com" not in titles


def test_general_nav_shows_daemon_pages_for_mature_config_once_sb_configured(
    tmp_path, monkeypatch
):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("LOXONE_IP", "192.168.178.20")
    monkeypatch.setenv("LOXONE_USER", "earnie")
    monkeypatch.setenv("LOXONE_PASS", "secret")
    _write(
        config_dir / "config.json",
        {"flexible_consumers": [{"id": "swimspa", "name": "SwimSpa"}]},
    )
    _write(config_dir / "components.json", {"batteries": [], "pv_systems": []})
    _write(config_dir / "house_profiles.json", {"profiles": []})
    _write(
        config_dir / "tariffs.json",
        {"import_tariffs": [], "export_tariffs": []},
    )

    specs = build_page_specs(["live_environment"])
    titles = [spec.title for spec in specs]

    assert "Smarthome-Backend" in titles
    assert "Optimierer-Dienst" in titles
    assert "EHAL-Com" in titles


def test_scenario_editor_after_house_config_ready(tmp_path, monkeypatch):
    config_dir = _bind_config_paths(tmp_path, monkeypatch)
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.delenv("LOXONE_USER", raising=False)
    monkeypatch.delenv("LOXONE_PASS", raising=False)
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
            "pv_system_ids": [],
            "import_tariff_id": "",
            "export_tariff_id": "",
            "house_profile_id": "efh",
        },
    )

    specs = build_page_specs(["scenario_explorer"])
    titles = [spec.title for spec in specs]

    assert titles == [
        "Hauskonfigurator",
        "Szenarienkonfigurator",
        "Smarthome-Backend",
    ]
    assert "Szenario-Explorer" not in titles
    assert "Live-Konfiguration" not in titles


def test_scenario_explorer_visible_when_planning_ready(tmp_path, monkeypatch):
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
            "import_tariffs": [{"id": "imp", "label": "Import", "type": "spot_hourly", "land": "AT"}],
            "export_tariffs": [
                {"id": "exp", "label": "Export", "type": "fixed", "k_push_cent": 3.7}
            ],
        },
    )
    _write_live_scenario(
        config_dir,
        {
            "battery_id": "bat",
            "pv_system_ids": ["pv"],
            "house_profile_id": "efh",
            "import_tariff_id": "imp",
            "export_tariff_id": "exp",
        },
    )

    specs = build_page_specs(["scenario_explorer"])
    titles = [spec.title for spec in specs]

    assert "Szenario-Explorer" in titles
