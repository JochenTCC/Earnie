"""Tests für zentrale Runtime-Auflösung in config.py (1.26.0 P2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import Config


def _write_minimal_greenfield_config(config_dir) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (repo_root / "config" / "config.minimal.json").read_text(encoding="utf-8")
    )
    (config_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    (config_dir / "house_profiles.json").write_text(
        json.dumps({"profiles": []}),
        encoding="utf-8",
    )
    (config_dir / "tariffs.json").write_text(
        json.dumps({"import_tariffs": [], "export_tariffs": []}),
        encoding="utf-8",
    )


def _write_id_only_config(config_dir, *, battery_wear_enabled: bool = False) -> None:
    battery = {
        "id": "home_5kwh",
        "label": "5 kWh",
        "battery_capacity_kwh": 5.0,
        "battery_max_power_kw": 2.5,
        "battery_efficiency": 0.97,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "threshold_power": 0.05,
    }
    if battery_wear_enabled:
        battery["battery_wear"] = {
            "enabled": True,
            "replacement_cost_euro": 1500,
            "expected_cycles": 6000,
            "cycle_cost_fraction": 0.5,
        }
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "eauto_milp": {
                    "live_modus_a_min_remaining_kwh": 2.8,
                    "tie_break_on_epsilon": 0.001,
                    "tie_break_time_epsilon": 0.0001,
                },
                "system": {"global_timeout": 10, "loop_timeout": 900},
                "loxone_blocks": {
                    "soc_name": "Battery_SOC",
                    "pv_counter_name": "PV_Counter",
                    "log_filename": "Verbrauch.csv",
                    "pv_tuning_log_file": "runtime/pv_accuracy_log.csv",
                    "pv_power_name": "PV_Act",
                    "battery_power_name": "Battery_Act",
                    "grid_power_name": "Grid_Act",
                    "target_soc_name": "Target_SoC",
                    "target_charge_power_name": "Target_Charge",
                    "target_discharge_power_name": "Target_Discharge",
                    "control_cmd_name": "Control_Cmd",
                },
                "planning_horizon": {"mode": "sunset_window"},
                "file_paths_battery_simulation": {
                    "path_cons_data": "runtime/cons_data_hourly.csv"
                },
                "runtime_settings": {
                    "battery_id": "home_5kwh",
                    "pv_system_id": "roof",
                    "import_tariff_id": "fixed_imp",
                    "export_tariff_id": "monthly_exp",
                    "house_profile_id": "efh",
                },
                "batteries": [battery],
                "pv_systems": [
                    {
                        "id": "roof",
                        "label": "Dach",
                        "kwp": 10.0,
                        "pv_tilt": 30,
                        "pv_azimuth": 180,
                    }
                ],
                "flexible_consumers": [],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "house_profiles.json").write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "efh",
                        "label": "EFH",
                        "annual_kwh": 4000,
                        "latitude": 48.2,
                        "longitude": 11.0,
                        "consumers": [
                            {
                                "id": "heat",
                                "type": "thermal_annual",
                                "nominal_power_kw": 3.0,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "tariffs.json").write_text(
        json.dumps(
            {
                "import_tariffs": [
                    {
                        "id": "fixed_imp",
                        "label": "Fix",
                        "type": "fixed_cent",
                        "fix_cent_kwh": 37.0,
                    }
                ],
                "export_tariffs": [
                    {
                        "id": "monthly_exp",
                        "label": "Monatlich",
                        "type": "monthly_table",
                        "monthly_rates": [
                            {"year": 2025, "month": 6, "tariff_cent_kwh": 5.5},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_config_loads_id_only_runtime_settings(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=True)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )

    assert cfg.PV_KWP == pytest.approx(10.0)
    assert cfg.BATTERY_CAPACITY_KWH == pytest.approx(5.0)
    assert cfg.FEED_IN_MODE == "fixed"

    resolved = cfg.get_resolved_runtime_settings()
    assert resolved["battery_capacity_kwh"] == pytest.approx(5.0)
    assert resolved["latitude"] == pytest.approx(48.2)
    assert resolved["longitude"] == pytest.approx(11.0)
    assert resolved["timezone_name"] == "Europe/Berlin"
    assert resolved.get("_house_profile") is not None
    assert resolved.get("_monthly_fixed_tariffs") is not None
    assert cfg.get_battery_wear_cent_per_kwh(5.0) == pytest.approx(2.5, rel=1e-3)


def test_battery_wear_requires_entity_config_when_battery_id_set(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )

    with pytest.raises(ValueError, match="battery_wear fehlt"):
        cfg.get_battery_wear_cent_per_kwh(5.0)
    resolved = cfg.get_resolved_runtime_settings()
    assert "_battery_wear" not in resolved


def test_backtesting_feed_in_settings_uses_resolved_baseline(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=True)
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps({"cbc_gap_rel": 0.1, "scenarios": []}),
        encoding="utf-8",
    )

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )

    settings = cfg.get_backtesting_feed_in_settings()
    assert settings.mode == "fixed"
    assert settings.monthly_fixed_tariffs is not None
    assert settings.k_push_cent == pytest.approx(0.0)


def test_backtesting_baseline_uses_same_resolution_path(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=True)
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps({"cbc_gap_rel": 0.1, "scenarios": []}),
        encoding="utf-8",
    )

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )

    baseline = cfg.get_backtesting_scenarios()["runtime_settings"]
    live = cfg.get_resolved_runtime_settings()
    assert baseline["pv_kwp"] == live["pv_kwp"]
    assert baseline["battery_capacity_kwh"] == live["battery_capacity_kwh"]


def test_config_defers_runtime_params_during_incomplete_greenfield(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_minimal_greenfield_config(config_dir)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )

    assert cfg.is_runtime_params_deferred() is True
    assert cfg.LATITUDE == pytest.approx(48.2)
    assert cfg.PLANNING_TIMEZONE == "Europe/Vienna"
    assert not hasattr(cfg, "K_PUSH_CENT") or getattr(cfg, "K_PUSH_CENT", None) is None

    with pytest.raises(RuntimeError, match="Planungs-Konfiguration unvollständig"):
        cfg.require_runtime_params_loaded()


def test_config_loads_full_params_after_planning_complete(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )

    assert cfg.is_runtime_params_deferred() is False
    assert cfg.PV_KWP == pytest.approx(10.0)
    cfg.require_runtime_params_loaded()


def test_update_runtime_settings_accepts_id_refs_only(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )

    cfg.update_runtime_settings({"battery_id": "home_5kwh"})

    reloaded = Config(
        config_path=str(config_dir / "config.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )
    runtime = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))[
        "runtime_settings"
    ]
    assert runtime["battery_id"] == "home_5kwh"
    assert reloaded.BATTERY_CAPACITY_KWH == pytest.approx(5.0)


def test_update_runtime_settings_rejects_geo_fields(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )

    with pytest.raises(KeyError, match="Hausprofil"):
        cfg.update_runtime_settings({"latitude": 47.5})

    with pytest.raises(KeyError, match="Hausprofil"):
        cfg.update_runtime_settings({"timezone_name": "Europe/Berlin"})


def test_update_runtime_settings_rejects_flat_pv_fields(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        require_loxone_credentials=False,
    )

    with pytest.raises(KeyError, match="deprecated flaches Feld"):
        cfg.update_runtime_settings({"PV_KWP": 12.0})

    with pytest.raises(KeyError, match="deprecated flaches Feld"):
        cfg.update_runtime_settings({"battery_capacity_kwh": 8.0})

