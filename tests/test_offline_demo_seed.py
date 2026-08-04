# tests/test_offline_demo_seed.py
"""Offline demo seed: fill empty live-scenario refs when EARNIE_OFFLINE=1."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime_store import bootstrap, offline_demo_seed
from settings import config_loaders


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _prepare_cloud_like(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "earnie_env" / "config"
    runtime_dir = tmp_path / "earnie_env" / "runtime"
    config_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    monkeypatch.setenv("EARNIE_ENV_PATH", str(tmp_path / "earnie_env"))
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir))
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir))
    monkeypatch.setenv(
        "EARNIE_HOUSE_PROFILES_PATH", str(config_dir / "house_profiles.json")
    )
    monkeypatch.setenv(
        "EARNIE_TARIFFS_PATH", str(config_dir / "tariffs.json")
    )
    monkeypatch.setenv(
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    monkeypatch.setenv(
        "EARNIE_COMPONENTS_PATH", str(config_dir / "components.json")
    )
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(runtime_dir))
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.setenv("EARNIE_OFFLINE", "1")

    _write_json(
        config_dir / "config.json",
        {
            "live_scenario_id": "live",
            "flexible_consumers": [],
            "planning_horizon": {"mode": "sunrise_window"},
            "loxone_blocks": {
                "soc_name": "Battery_SOC",
                "pv_power_name": "PV_Act",
                "battery_power_name": "Battery_Act",
                "grid_power_name": "Grid_Act",
                "target_charge_power_name": "Target_Charge",
                "target_discharge_power_name": "Target_Discharge",
                "control_cmd_name": "Control_Cmd",
            },
            "system": {"global_timeout": 10, "loop_timeout": 900},
            "ui": {"streamlit_port": 8501},
            "market_prices": {"missing_price_strategy": "forecast"},
        },
    )
    _write_json(
        config_dir / "backtesting_scenarios.json",
        {
            "cbc_gap_rel": 0.1,
            "scenarios": [
                {
                    "id": "live",
                    "label": "Live",
                    "settings": {
                        "battery_id": "",
                        "pv_system_ids": [],
                        "import_tariff_id": "",
                        "export_tariff_id": "",
                        "house_profile_id": "",
                    },
                }
            ],
        },
    )
    _write_json(
        config_dir / "components.json",
        {
            "batteries": [
                {
                    "id": "10_kwh_speicher",
                    "label": "10 kWh",
                    "battery_capacity_kwh": 10.0,
                    "battery_max_power_kw": 5.0,
                    "battery_efficiency": 0.97,
                    "battery_min_soc": 10.0,
                    "battery_max_soc": 100.0,
                    "threshold_power": 0.05,
                }
            ],
            "pv_systems": [{"id": "dach_sued", "label": "Dach", "kwp": 6.0, "pv_tilt": 18, "pv_azimuth": 26}],
        },
    )
    _write_json(
        config_dir / "tariffs.json",
        {
            "import_tariffs": [
                {"id": "awattar_at", "label": "aWATTar", "type": "spot_hourly", "land": "AT"},
            ],
            "export_tariffs": [
                {"id": "fixed_37ct", "label": "Fix", "type": "fixed", "k_push_cent": 3.7},
            ],
        },
    )
    _write_json(
        config_dir / "house_profiles.json",
        {
            "profiles": [
                {
                    "id": "example_efh",
                    "label": "Demo",
                    "annual_kwh": 12000.0,
                    "latitude": 48.2,
                    "longitude": 16.3,
                    "consumers": [
                        {
                            "id": "ev",
                            "label": "EV",
                            "type": "ev",
                            "nominal_power_kw": 3.5,
                            "battery_capacity_kwh": 17.0,
                            "min_power_kw": 1.4,
                            "loxone_inputs": {"power_name": "EV_P"},
                            "loxone_outputs": {"enable_name": "EV_En"},
                        }
                    ],
                }
            ]
        },
    )
    return tmp_path


def test_seed_fills_empty_live_refs(tmp_path, monkeypatch):
    _prepare_cloud_like(tmp_path, monkeypatch)

    assert offline_demo_seed.seed_offline_live_scenario() is True

    doc = json.loads(
        (tmp_path / "earnie_env" / "config" / "backtesting_scenarios.json").read_text(
            encoding="utf-8"
        )
    )
    settings = doc["scenarios"][0]["settings"]
    assert settings["battery_id"] == "10_kwh_speicher"
    assert settings["pv_system_ids"] == ["dach_sued"]
    assert settings["import_tariff_id"] == "awattar_at"
    assert settings["export_tariff_id"] == "fixed_37ct"
    assert settings["house_profile_id"] == "example_efh"
    assert offline_demo_seed.live_scenario_refs_incomplete() is False


def test_seed_does_not_overwrite_existing_refs(tmp_path, monkeypatch):
    root = _prepare_cloud_like(tmp_path, monkeypatch)
    path = root / "earnie_env" / "config" / "backtesting_scenarios.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["scenarios"][0]["settings"]["export_tariff_id"] = "fixed_37ct"
    doc["scenarios"][0]["settings"]["battery_id"] = "keep_me"
    path.write_text(json.dumps(doc), encoding="utf-8")

    offline_demo_seed.seed_offline_live_scenario()

    settings = json.loads(path.read_text(encoding="utf-8"))["scenarios"][0]["settings"]
    assert settings["battery_id"] == "keep_me"
    assert settings["export_tariff_id"] == "fixed_37ct"
    assert settings["import_tariff_id"] == "awattar_at"


def test_seed_noop_without_offline(tmp_path, monkeypatch):
    _prepare_cloud_like(tmp_path, monkeypatch)
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)

    assert offline_demo_seed.seed_offline_live_scenario() is False


def test_bootstrap_seeds_when_offline(tmp_path, monkeypatch):
    root = _prepare_cloud_like(tmp_path, monkeypatch)
    # Templates for bootstrap copy paths (already have json files; runtime dirs exist)
    share = root / "share" / "config"
    share.mkdir(parents=True)
    (share / ".env.example").write_text("LOXONE_IP=1.2.3.4\n", encoding="utf-8")

    bootstrap.run()

    settings = json.loads(
        (root / "earnie_env" / "config" / "backtesting_scenarios.json").read_text(
            encoding="utf-8"
        )
    )["scenarios"][0]["settings"]
    assert settings["export_tariff_id"] == "fixed_37ct"


def test_defer_when_offline_and_incomplete(tmp_path, monkeypatch):
    _prepare_cloud_like(tmp_path, monkeypatch)
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    raw = json.loads(
        (tmp_path / "earnie_env" / "config" / "config.json").read_text(encoding="utf-8")
    )
    assert (
        config_loaders.should_defer_runtime_params(
            raw,
            components_path=str(tmp_path / "earnie_env" / "config" / "components.json"),
            tariffs_path=str(tmp_path / "earnie_env" / "config" / "tariffs.json"),
            house_profiles_path=str(
                tmp_path / "earnie_env" / "config" / "house_profiles.json"
            ),
            backtesting_scenarios_path=str(
                tmp_path / "earnie_env" / "config" / "backtesting_scenarios.json"
            ),
        )
        is True
    )
