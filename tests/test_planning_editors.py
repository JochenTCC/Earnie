"""Tests für Planungs-Editoren und ID-Generierung (1.24.e)."""
from __future__ import annotations

import json

import pytest

from house_config.id_slug import slug_id
from house_config.profiles_store import load_house_profiles_document
from data.heating_need import specific_heating_kwh_m2
from ui import setup_readiness
from ui.house_config_io import (
    get_planning_tariff_selection,
    save_planning_tariff_selection,
    upsert_battery,
    upsert_house_profile,
    upsert_pv_system,
)
from ui.house_config_profile_form import (
    _consumer_type_options,
    _default_additional_consumer,
    _default_consumer,
    _profile_session_scope,
)


def _bind_paths(tmp_path, monkeypatch: pytest.MonkeyPatch):
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


def test_slug_id_normalizes_umlauts_and_collisions():
    assert slug_id("Mein Haushalt") == "mein_haushalt"
    assert slug_id("Wärmepumpe") == "waermepumpe"
    assert slug_id("Mein Haushalt", existing={"mein_haushalt"}) == "mein_haushalt_2"


def test_specific_heating_kwh_m2_hwb_override():
    assert specific_heating_kwh_m2(3, hwb_kwh_m2=55.0) == 55.0
    assert specific_heating_kwh_m2(3) == 80.0


def test_upsert_pv_and_battery_persist(tmp_path, monkeypatch):
    config_dir = _bind_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("ui.house_config_io.config.reinit_config", lambda **kwargs: None)
    config_dir.joinpath("config.json").write_text(
        json.dumps(
            {
                "runtime_settings": {
                    "k_push_cent": 3.5,
                    "feed_in_mode": "fixed",
                    "pv_tilt": 25,
                    "pv_azimuth": 0,
                    "pv_kwp": 0,
                    "battery_max_power_kw": 0,
                    "battery_efficiency": 0.97,
                    "battery_capacity_kwh": 0,
                    "battery_min_soc": 10,
                    "battery_max_soc": 100,
                    "threshold_power": 0.05,
                    "latitude": 48.2,
                    "longitude": 16.37,
                    "timezone_name": "Europe/Vienna",
                    "import_tariff_id": "",
                    "export_tariff_id": "",
                },
                "batteries": [],
                "pv_systems": [],
                "flexible_consumers": [],
                "awattar": {"url": "https://example.test"},
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
                "file_paths_battery_simulation": {"path_cons_data": "runtime/cons_data_hourly.csv"},
            }
        ),
        encoding="utf-8",
    )

    upsert_pv_system({"label": "Dach Süd", "kwp": 9.5, "pv_tilt": 30, "pv_azimuth": 0})
    upsert_battery(
        {
            "label": "Speicher 5kWh",
            "battery_capacity_kwh": 5.0,
            "battery_max_power_kw": 2.5,
            "battery_efficiency": 0.97,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "threshold_power": 0.05,
        }
    )

    payload = json.loads(config_dir.joinpath("config.json").read_text(encoding="utf-8"))
    assert payload["pv_systems"][0]["id"] == "dach_sued"
    assert payload["batteries"][0]["battery_capacity_kwh"] == 5.0


def test_save_planning_tariff_selection(tmp_path, monkeypatch):
    config_dir = _bind_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("ui.house_config_io.config.reinit_config", lambda **kwargs: None)
    config_dir.joinpath("config.json").write_text(
        json.dumps({"runtime_settings": {}, "flexible_consumers": []}),
        encoding="utf-8",
    )

    save_planning_tariff_selection("fixed_25ct", "fixed_37ct")
    assert get_planning_tariff_selection() == ("fixed_25ct", "fixed_37ct")


def test_planning_ready_with_selected_tariffs(tmp_path, monkeypatch):
    config_dir = _bind_paths(tmp_path, monkeypatch)
    config_dir.joinpath("config.json").write_text(
        json.dumps(
            {
                "batteries": [{"id": "bat"}],
                "pv_systems": [{"id": "pv"}],
                "flexible_consumers": [],
                "runtime_settings": {
                    "battery_id": "bat",
                    "pv_system_id": "pv",
                    "house_profile_id": "efh",
                    "import_tariff_id": "imp",
                    "export_tariff_id": "exp",
                },
            }
        ),
        encoding="utf-8",
    )
    config_dir.joinpath("house_profiles.json").write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "efh",
                        "annual_kwh": 4000,
                        "consumers": [{"id": "wp", "type": "thermal_annual", "living_area_m2": 100}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config_dir.joinpath("tariffs.json").write_text(
        json.dumps(
            {
                "import_tariffs": [
                    {"id": "imp", "label": "Import", "type": "awattar"},
                ],
                "export_tariffs": [
                    {"id": "exp", "label": "Export", "type": "fixed", "k_push_cent": 3.7},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert setup_readiness.is_planning_ready() is True


def test_house_profile_hwb_normalization(tmp_path):
    path = tmp_path / "house_profiles.json"
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "home",
                        "annual_kwh": 5000,
                        "consumers": [
                            {
                                "id": "heat",
                                "label": "Wärme",
                                "type": "thermal_annual",
                                "nominal_power_kw": 2.0,
                                "living_area_m2": 120,
                                "building_class": 3,
                                "hwb_kwh_m2": 62.0,
                                "heat_pump_type": "luft",
                                "persons": 2,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doc = load_house_profiles_document(str(path))
    thermal = doc["profiles"]["home"]["consumers"][0]["thermal"]
    assert thermal["hwb_kwh_m2"] == 62.0


def test_default_consumer_is_thermal():
    consumer = _default_consumer()
    assert consumer["type"] == "thermal_annual"
    assert consumer["label"] == "Haus Wärme"
    assert consumer["living_area_m2"] == 120.0


def test_default_additional_consumer_is_generic():
    consumer = _default_additional_consumer()
    assert consumer["type"] == "generic"
    assert consumer["label"] == "Verbraucher"
    assert "schedule" in consumer


def test_consumer_type_options_thermal_only_on_first():
    assert "thermal_annual" in _consumer_type_options(0)
    assert "thermal_annual" not in _consumer_type_options(1)
    assert _consumer_type_options(1) == ["generic", "ev"]


def test_profile_rejects_thermal_on_second_consumer(tmp_path):
    path = tmp_path / "house_profiles.json"
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "home",
                        "annual_kwh": 5000,
                        "consumers": [
                            {"id": "heat", "type": "generic", "annual_kwh": 1000},
                            {
                                "id": "heat2",
                                "type": "thermal_annual",
                                "living_area_m2": 100,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Verbraucher 1"):
        load_house_profiles_document(str(path))
    assert _profile_session_scope("— neu —", is_new=True) == "__new__"
    assert _profile_session_scope("example_efh", is_new=False) == "example_efh"


def test_upsert_two_consumers_roundtrip(tmp_path, monkeypatch):
    config_dir = _bind_paths(tmp_path, monkeypatch)
    path = config_dir / "house_profiles.json"
    upsert_house_profile(
        {
            "id": "home",
            "label": "Test",
            "annual_kwh": 8000.0,
            "consumers": [
                {
                    "id": "pool",
                    "label": "Pool",
                    "type": "generic",
                    "nominal_power_kw": 2.0,
                    "annual_kwh": 1200.0,
                },
                {
                    "id": "ev",
                    "label": "E-Auto",
                    "type": "ev",
                    "nominal_power_kw": 3.5,
                    "min_power_kw": 1.4,
                    "min_on_quarterhours": 4,
                    "battery_capacity_kwh": 60.0,
                    "charging_schedule": {
                        "target_soc_percent": 100.0,
                        "charging_efficiency": 0.95,
                        "forecast_when_absent": True,
                        "weekday": {
                            "car_available_from_hour": 18,
                            "ready_by_hour": 7,
                            "daily_rest_soc": 40.0,
                        },
                        "weekend": {
                            "car_available_from_hour": 20,
                            "ready_by_hour": 9,
                            "daily_rest_soc": 30.0,
                        },
                    },
                },
            ],
        }
    )
    doc = load_house_profiles_document(str(path))
    consumers = doc["profiles"]["home"]["consumers"]
    assert len(consumers) == 2
    assert {consumer["id"] for consumer in consumers} == {"pool", "ev"}
