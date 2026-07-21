"""Tests für zentrale Live-Szenario-Auflösung in config.py (1.26.0 P2 / 2.0 P2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import Config
from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID


def _write_live_scenarios(config_dir, *, settings: dict | None = None) -> None:
    live_settings = settings or {
        "battery_id": "home_5kwh",
        "pv_system_id": "roof",
        "import_tariff_id": "fixed_imp",
        "export_tariff_id": "monthly_exp",
        "house_profile_id": "efh",
    }
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps(
            {
                "cbc_gap_rel": 0.1,
                "scenarios": [
                    {
                        "id": DEFAULT_LIVE_SCENARIO_ID,
                        "label": "Live",
                        "settings": live_settings,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_minimal_greenfield_config(config_dir) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (repo_root / "share" / "config" / "config.minimal.json").read_text(encoding="utf-8")
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
    (config_dir / "components.json").write_text(
        json.dumps({"batteries": [], "pv_systems": []}),
        encoding="utf-8",
    )
    _write_live_scenarios(config_dir, settings={
        "battery_id": "",
        "pv_system_id": "",
        "import_tariff_id": "",
        "export_tariff_id": "",
        "house_profile_id": "",
    })


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
                "live_scenario_id": DEFAULT_LIVE_SCENARIO_ID,
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
                "planning_horizon": {"mode": "sunrise_window"},
                "scenario_explorer_conf": {
                    "path_cons_data": "runtime/cons_data_hourly.csv"
                },
                "flexible_consumers": [],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "components.json").write_text(
        json.dumps(
            {
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
    _write_live_scenarios(config_dir)


def test_config_loads_id_only_live_scenario(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=True)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
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
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
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

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )

    settings = cfg.get_backtesting_feed_in_settings()
    assert settings.mode == "fixed"
    assert settings.monthly_fixed_tariffs is not None
    assert settings.k_push_cent == pytest.approx(0.0)


def test_live_scenario_in_backtesting_scenarios(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=True)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )

    scenarios = cfg.get_backtesting_scenarios()
    assert DEFAULT_LIVE_SCENARIO_ID in scenarios
    live = scenarios[DEFAULT_LIVE_SCENARIO_ID]
    resolved = cfg.get_resolved_runtime_settings()
    assert live["pv_kwp"] == resolved["pv_kwp"]
    assert live["battery_capacity_kwh"] == resolved["battery_capacity_kwh"]


def test_config_rejects_legacy_runtime_settings_block(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir)
    payload = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    payload["runtime_settings"] = {"battery_id": "home_5kwh"}
    (config_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="runtime_settings"):
        Config(
            config_path=str(config_dir / "config.json"),
            backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
            tariffs_path=str(config_dir / "tariffs.json"),
            house_profiles_path=str(config_dir / "house_profiles.json"),
            require_loxone_credentials=False,
        )


def test_config_defers_runtime_params_during_incomplete_greenfield(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_minimal_greenfield_config(config_dir)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
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
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )

    assert cfg.is_runtime_params_deferred() is False
    assert cfg.PV_KWP == pytest.approx(10.0)
    cfg.require_runtime_params_loaded()


def test_config_loads_zero_pv_without_pv_system(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)
    components_doc = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    components_doc["pv_systems"] = []
    (config_dir / "components.json").write_text(json.dumps(components_doc), encoding="utf-8")
    scenarios_doc = json.loads(
        (config_dir / "backtesting_scenarios.json").read_text(encoding="utf-8")
    )
    scenarios_doc["scenarios"][0]["settings"]["pv_system_id"] = ""
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps(scenarios_doc),
        encoding="utf-8",
    )

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )

    assert cfg.is_runtime_params_deferred() is False
    assert cfg.PV_KWP == pytest.approx(0.0)
    assert cfg.PV_TILT == pytest.approx(0.0)
    assert cfg.PV_AZIMUTH == pytest.approx(0.0)
    cfg.require_runtime_params_loaded()


def test_backtesting_scenario_without_battery_resolves_zero_flat(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)
    scenarios_doc = {
        "cbc_gap_rel": 0.1,
        "scenarios": [
            {
                "id": DEFAULT_LIVE_SCENARIO_ID,
                "label": "Live",
                "settings": {
                    "battery_id": "home_5kwh",
                    "pv_system_id": "roof",
                    "import_tariff_id": "fixed_imp",
                    "export_tariff_id": "monthly_exp",
                    "house_profile_id": "efh",
                },
            },
            {
                "id": "no_battery",
                "label": "No Battery",
                "settings": {
                    "import_tariff_id": "fixed_imp",
                    "export_tariff_id": "monthly_exp",
                    "house_profile_id": "efh",
                },
            },
        ],
    }
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps(scenarios_doc),
        encoding="utf-8",
    )

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )

    from simulation.engine import _scenario_to_battery_params

    scenario = cfg.get_backtesting_scenarios()["no_battery"]
    battery = _scenario_to_battery_params(scenario)
    assert battery["battery_capacity_kwh"] == pytest.approx(0.0)
    assert battery["max_power_kw"] == pytest.approx(0.0)


def test_update_live_scenario_settings_accepts_id_refs_only(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )

    cfg.update_live_scenario_settings({"battery_id": "home_5kwh"})

    reloaded = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )
    scenarios_doc = json.loads(
        (config_dir / "backtesting_scenarios.json").read_text(encoding="utf-8")
    )
    live = next(s for s in scenarios_doc["scenarios"] if s["id"] == DEFAULT_LIVE_SCENARIO_ID)
    assert live["settings"]["battery_id"] == "home_5kwh"
    assert reloaded.BATTERY_CAPACITY_KWH == pytest.approx(5.0)


def test_update_live_scenario_settings_rejects_geo_fields(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )

    with pytest.raises(KeyError, match="Hausprofil"):
        cfg.update_live_scenario_settings({"latitude": 47.5})

    with pytest.raises(KeyError, match="Hausprofil"):
        cfg.update_live_scenario_settings({"timezone_name": "Europe/Berlin"})


def test_update_live_scenario_settings_rejects_flat_pv_fields(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )

    with pytest.raises(KeyError, match="deprecated flaches Feld"):
        cfg.update_live_scenario_settings({"PV_KWP": 12.0})

    with pytest.raises(KeyError, match="deprecated flaches Feld"):
        cfg.update_live_scenario_settings({"battery_capacity_kwh": 8.0})


def test_set_live_scenario_id_persists_and_reloads(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)
    scenarios_path = config_dir / "backtesting_scenarios.json"
    scenarios_doc = json.loads(scenarios_path.read_text(encoding="utf-8"))
    scenarios_doc["scenarios"].append(
        {
            "id": "alt",
            "label": "Alternative",
            "settings": {
                "battery_id": "home_5kwh",
                "pv_system_id": "roof",
                "import_tariff_id": "fixed_imp",
                "export_tariff_id": "monthly_exp",
                "house_profile_id": "efh",
            },
        }
    )
    scenarios_path.write_text(json.dumps(scenarios_doc), encoding="utf-8")

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(scenarios_path),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )
    assert cfg.get_live_scenario_id() == DEFAULT_LIVE_SCENARIO_ID

    cfg.set_live_scenario_id("alt")

    config_doc = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    assert config_doc["live_scenario_id"] == "alt"
    assert cfg.get_live_scenario_id() == "alt"


def test_set_live_scenario_id_rejects_unknown(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    _write_id_only_config(config_dir, battery_wear_enabled=False)

    cfg = Config(
        config_path=str(config_dir / "config.json"),
        backtesting_scenarios_path=str(config_dir / "backtesting_scenarios.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
        components_path=str(config_dir / "components.json"),
        require_loxone_credentials=False,
    )

    with pytest.raises(ValueError, match="Unbekanntes Szenario"):
        cfg.set_live_scenario_id("missing")
