"""Tests für Empfehlungsgeräte (Hausprofil appliance_recommendation)."""
from __future__ import annotations

import json

import pytest

import config
from config import Config, reinit_config


def test_get_appliances_empty_without_block():
    # Fixture-Config (conftest) ohne Hausprofil-Geräte → leere Liste.
    assert config.get_appliances() == []


def test_normalize_loxone_appliance():
    spec = Config._normalize_appliance(
        {
            "id": "waschmaschine",
            "name": "Waschmaschine",
            "power_source": "loxone",
            "loxone_power_name": "Leistung Waschmaschine",
            "default_power_kw": 2.0,
            "default_runtime_h": 2.0,
        },
        0,
    )
    assert spec["power_source"] == "loxone"
    assert spec["loxone_power_name"] == "Leistung Waschmaschine"
    assert spec["default_runtime_h"] == 2.0
    assert spec["default_power_kw"] == 2.0


def test_loxone_appliance_requires_default_power():
    with pytest.raises(ValueError, match="default_power_kw"):
        Config._normalize_appliance(
            {
                "id": "waschmaschine",
                "name": "Waschmaschine",
                "power_source": "loxone",
                "loxone_power_name": "Leistung Waschmaschine",
            },
            0,
        )


def test_normalize_manual_appliance():
    spec = Config._normalize_appliance(
        {
            "id": "geschirrspueler",
            "name": "Geschirrspüler",
            "power_source": "manual",
            "default_power_kw": 1.2,
        },
        0,
    )
    assert spec["power_source"] == "manual"
    assert spec["default_power_kw"] == 1.2
    assert spec["loxone_power_name"] == ""


def test_loxone_appliance_requires_merker_name():
    with pytest.raises(ValueError, match="loxone_power_name"):
        Config._normalize_appliance(
            {"id": "x", "name": "X", "power_source": "loxone"}, 0
        )


def test_invalid_power_source_raises():
    with pytest.raises(ValueError, match="power_source"):
        Config._normalize_appliance(
            {"id": "x", "name": "X", "power_source": "hue"}, 0
        )


def test_missing_id_raises():
    with pytest.raises(ValueError, match="id fehlt"):
        Config._normalize_appliance(
            {"name": "X", "power_source": "manual"}, 3
        )


def test_negative_runtime_raises():
    with pytest.raises(ValueError, match="default_runtime_h"):
        Config._normalize_appliance(
            {"id": "x", "name": "X", "power_source": "manual", "default_runtime_h": 0},
            0,
        )


def test_root_appliances_block_rejected(tmp_path, monkeypatch):
    base = json.loads(open(config.CONFIG_JSON_PATH, encoding="utf-8").read())
    base["appliances"] = []
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(cfg_path))
    with pytest.raises(ValueError, match="appliances"):
        reinit_config()


def test_root_eauto_milp_block_rejected(tmp_path, monkeypatch):
    base = json.loads(open(config.CONFIG_JSON_PATH, encoding="utf-8").read())
    base["eauto_milp"] = {
        "live_modus_a_min_remaining_kwh": 2.8,
        "tie_break_on_epsilon": 0.001,
        "tie_break_time_epsilon": 0.0001,
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(cfg_path))
    with pytest.raises(ValueError, match="eauto_milp"):
        reinit_config()


@pytest.mark.parametrize(
    "block_key,block_value",
    [
        ("file_paths_battery_simulation", {"path_cons_data": "runtime/cons_data_hourly.csv"}),
        ("awattar", {}),
        ("battery_wear", {"enabled": False}),
        ("batteries", []),
        ("pv_systems", []),
        ("eauto_milp", {"live_modus_a_min_remaining_kwh": 1.0}),
    ],
)
def test_reject_legacy_config_blocks_unit(block_key, block_value):
    from settings.legacy_config_gates import reject_legacy_config_blocks

    with pytest.raises(ValueError, match=block_key):
        reject_legacy_config_blocks({block_key: block_value})


def test_reject_legacy_config_blocks_allows_clean_config():
    from settings.legacy_config_gates import reject_legacy_config_blocks

    reject_legacy_config_blocks({"system": {"global_timeout": 10}})


def test_reject_path_consumption_production_in_scenario_explorer_conf():
    from settings.legacy_config_gates import reject_legacy_config_blocks

    with pytest.raises(ValueError, match="path_consumption"):
        reject_legacy_config_blocks(
            {
                "scenario_explorer_conf": {
                    "path_cons_data": "runtime/cons_data_hourly.csv",
                    "path_consumption": "c.csv",
                    "path_production": "p.csv",
                }
            }
        )


def test_reject_legacy_runtime_settings_block_unit():
    from settings.legacy_config_gates import reject_legacy_runtime_settings_block

    with pytest.raises(ValueError, match="runtime_settings"):
        reject_legacy_runtime_settings_block({"runtime_settings": {"battery_id": "x"}})


def test_reject_legacy_runtime_settings_block_allows_clean_config():
    from settings.legacy_config_gates import reject_legacy_runtime_settings_block

    reject_legacy_runtime_settings_block({"live_scenario_id": "live"})


@pytest.mark.parametrize(
    "block_key,block_value",
    [
        ("awattar", {}),
        ("battery_wear", {"enabled": False}),
        ("batteries", []),
        ("pv_systems", []),
    ],
)
def test_root_legacy_config_blocks_rejected(
    tmp_path, monkeypatch, block_key, block_value
):
    base = json.loads(open(config.CONFIG_JSON_PATH, encoding="utf-8").read())
    base[block_key] = block_value
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(cfg_path))
    with pytest.raises(ValueError, match=block_key):
        reinit_config()


def test_update_appliance_defaults_roundtrip(tmp_path, monkeypatch):
    from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    base = json.loads(open(config.CONFIG_JSON_PATH, encoding="utf-8").read())
    cfg_path = config_dir / "config.json"
    cfg_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    profiles = {
        "profiles": [
            {
                "id": "example_efh",
                "label": "EFH",
                "annual_kwh": 4000.0,
                "consumers": [
                    {
                        "id": "waschmaschine",
                        "label": "Waschmaschine",
                        "type": "generic",
                        "nominal_power_kw": 2.0,
                        "earnie_role": "manual",
                        "schedule": {
                            "runs_per_week": 5,
                            "duration_h": 2.0,
                            "start_hour": 15,
                            "start_shift_h": 4.0,
                        },
                        "appliance_recommendation": {
                            "power_source": "manual",
                            "default_power_kw": 2.0,
                            "default_runtime_h": 2.0,
                        },
                    }
                ],
            }
        ]
    }
    (config_dir / "house_profiles.json").write_text(
        json.dumps(profiles), encoding="utf-8"
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
                    {"id": "fixed_exp", "label": "Fix", "type": "fixed", "k_push_cent": 3.5}
                ],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "components.json").write_text(
        json.dumps(
            {
                "batteries": [
                    {
                        "id": "home",
                        "label": "Home",
                        "battery_capacity_kwh": 5.0,
                        "battery_max_power_kw": 2.5,
                        "battery_efficiency": 0.97,
                        "battery_min_soc": 10.0,
                        "battery_max_soc": 100.0,
                        "threshold_power": 0.02,
                        "battery_wear": {"enabled": False},
                    }
                ],
                "pv_systems": [
                    {
                        "id": "roof",
                        "label": "Roof",
                        "kwp": 10.0,
                        "pv_tilt": 25,
                        "pv_azimuth": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": DEFAULT_LIVE_SCENARIO_ID,
                        "label": "Live",
                        "settings": {
                            "battery_id": "home",
                            "pv_system_id": "roof",
                            "import_tariff_id": "fixed_imp",
                            "export_tariff_id": "fixed_exp",
                            "house_profile_id": "example_efh",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_TARIFFS_PATH", str(config_dir / "tariffs.json")
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_COMPONENTS_PATH",
        str(config_dir / "components.json"),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    reinit_config()

    config.update_appliance_defaults("waschmaschine", power_kw=2.5, runtime_h=1.75)
    reinit_config()

    saved = json.loads(
        (config_dir / "house_profiles.json").read_text(encoding="utf-8")
    )
    consumer = saved["profiles"][0]["consumers"][0]
    assert consumer["appliance_recommendation"]["default_power_kw"] == 2.5
    assert consumer["appliance_recommendation"]["default_runtime_h"] == 1.75
    appliance = config.get_appliances()[0]
    assert appliance["default_power_kw"] == 2.5
    assert appliance["default_runtime_h"] == 1.75


def test_update_appliance_unknown_id_raises(tmp_path, monkeypatch):
    from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    base = json.loads(open(config.CONFIG_JSON_PATH, encoding="utf-8").read())
    cfg_path = config_dir / "config.json"
    cfg_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    (config_dir / "house_profiles.json").write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "example_efh",
                        "label": "EFH",
                        "annual_kwh": 4000.0,
                        "consumers": [],
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
                    {"id": "fixed_exp", "label": "Fix", "type": "fixed", "k_push_cent": 3.5}
                ],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "components.json").write_text(
        json.dumps(
            {
                "batteries": [
                    {
                        "id": "home",
                        "label": "Home",
                        "battery_capacity_kwh": 5.0,
                        "battery_max_power_kw": 2.5,
                        "battery_efficiency": 0.97,
                        "battery_min_soc": 10.0,
                        "battery_max_soc": 100.0,
                        "threshold_power": 0.02,
                        "battery_wear": {"enabled": False},
                    }
                ],
                "pv_systems": [
                    {
                        "id": "roof",
                        "label": "Roof",
                        "kwp": 10.0,
                        "pv_tilt": 25,
                        "pv_azimuth": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "backtesting_scenarios.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": DEFAULT_LIVE_SCENARIO_ID,
                        "label": "Live",
                        "settings": {
                            "battery_id": "home",
                            "pv_system_id": "roof",
                            "import_tariff_id": "fixed_imp",
                            "export_tariff_id": "fixed_exp",
                            "house_profile_id": "example_efh",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_TARIFFS_PATH", str(config_dir / "tariffs.json")
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_COMPONENTS_PATH",
        str(config_dir / "components.json"),
    )
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    reinit_config()
    with pytest.raises(KeyError, match="waschmaschine"):
        config.update_appliance_defaults("waschmaschine", power_kw=2.0, runtime_h=2.0)


def test_recommendation_appliances_from_house_profile():
    from settings.appliances import recommendation_appliances_from_profile

    profile = {
        "id": "example_efh",
        "consumers": [
            {
                "id": "waschmaschine",
                "label": "Waschmaschine",
                "type": "generic",
                "nominal_power_kw": 2.0,
                "earnie_role": "manual",
                "schedule": {
                    "runs_per_week": 5,
                    "duration_h": 2.0,
                    "start_hour": 15,
                    "start_shift_h": 4.0,
                },
                "appliance_recommendation": {
                    "power_source": "loxone",
                    "default_power_kw": 2.0,
                    "default_runtime_h": 2.0,
                },
                "loxone_inputs": {"power_name": "Leistung Waschmaschine"},
            }
        ],
    }
    appliances = recommendation_appliances_from_profile(profile)
    assert len(appliances) == 1
    assert appliances[0]["id"] == "waschmaschine"
    assert appliances[0]["name"] == "Waschmaschine"
    assert appliances[0]["default_runtime_h"] == 2.0
    assert appliances[0]["recommendation_horizon_h"] == 4
    assert appliances[0]["loxone_inputs"] == {"power_name": "Leistung Waschmaschine"}
