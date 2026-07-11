"""Tests für Hauskonfigurator-Entitäten, Tarife und Szenario-Auflösung (Version 1.24)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import config
from data.consumption_profiles import build_hourly_kw_profile
from house_config.baseload import compute_baseload_kwh, consumer_annual_kwh
from house_config.entity_resolution import (
    batteries_by_id,
    resolve_battery_into_settings,
    resolve_pv_into_settings,
)
from house_config.ev_profile import estimate_ev_annual_kwh, ev_hourly_kw_for_day
from house_config.profiles_store import load_house_profiles_document
from house_config.tariffs_store import load_tariffs_document
from optimizer.charging_context import hour_in_charging_window


def _sample_ev_consumer() -> dict:
    return {
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
    }


def test_batteries_by_id_from_fixture():
    batteries = batteries_by_id(config.CONFIG._raw_config)
    assert "test_battery" in batteries
    assert batteries["test_battery"]["battery_capacity_kwh"] == 8.0


def test_resolve_battery_into_settings():
    batteries = batteries_by_id(config.CONFIG._raw_config)
    resolved = resolve_battery_into_settings({"battery_id": "test_battery"}, batteries)
    assert resolved["battery_capacity_kwh"] == 8.0
    assert resolved["_battery_wear"]["enabled"] is True
    assert "battery_id" not in resolved


def test_battery_wear_cent_per_kwh_from_entity():
    from house_config.entity_resolution import battery_wear_cent_per_kwh

    batteries = batteries_by_id(config.CONFIG._raw_config)
    bat = batteries["test_battery"]
    wear = battery_wear_cent_per_kwh(bat)
    assert wear == pytest.approx(2.5, rel=1e-3)


def test_resolve_pv_into_settings():
    from house_config.entity_resolution import pv_systems_by_id

    pv_map = pv_systems_by_id(config.CONFIG._raw_config)
    resolved = resolve_pv_into_settings({"pv_system_id": "test_pv"}, pv_map)
    assert resolved["pv_kwp"] == 6.0


def test_scenario_entity_resolution():
    scenarios = config.get_backtesting_scenarios()
    assert "entity_test" in scenarios
    entity = scenarios["entity_test"]
    assert entity["battery_capacity_kwh"] == 8.0
    assert entity["pv_kwp"] == 6.0
    assert entity["feed_in_mode"] == "fixed"
    assert entity.get("_monthly_fixed_tariffs") is not None
    assert entity.get("_house_profile") is not None


def test_baseload_minimum_fraction():
    result = compute_baseload_kwh(4000, [{"annual_kwh": 3900, "type": "generic"}])
    assert result["baseload_kwh"] >= 200.0


def test_consumer_annual_kwh_flat_thermal():
    consumer = {
        "type": "thermal_annual",
        "living_area_m2": 120.0,
        "building_class": 3,
        "heat_pump_type": "luft",
        "persons": 2,
    }
    assert consumer_annual_kwh(consumer) > 0.0


def test_house_profile_thermal_annual():
    path = config.HOUSE_PROFILES_JSON_PATH
    doc = load_house_profiles_document(path)
    profile = doc["profiles"]["test_home"]
    assert profile["baseload_kwh"] >= profile["baseload_min_kwh"]
    hourly = build_hourly_kw_profile(profile, hours=168)
    assert len(hourly) == 168
    assert sum(hourly) > 0


def test_tariffs_document_fixture():
    doc = load_tariffs_document(config.TARIFFS_JSON_PATH)
    assert doc.get("catalog_as_of")
    assert "monthly_test" in doc["export_tariffs"]


def test_dach_tariffs_catalog():
    root = Path(__file__).resolve().parents[1]
    doc = load_tariffs_document(str(root / "config" / "tariffs.json"))
    assert doc.get("catalog_as_of") == "2026"
    assert len(doc["import_tariffs"]) == 33
    assert len(doc["export_tariffs"]) == 12
    assert "awattar_at" in doc["import_tariffs"]
    assert "dynamic_epex" in doc["export_tariffs"]


def test_import_monthly_table_tariff_normalization():
    from house_config.tariffs_store import normalize_tariffs_document

    doc = normalize_tariffs_document(
        {
            "import_tariffs": [
                {
                    "id": "monthly_import",
                    "label": "Monatlich",
                    "type": "monthly_table",
                    "monthly_rates": [
                        {"year": 2025, "month": 1, "tariff_cent_kwh": 20.0},
                    ],
                }
            ],
            "export_tariffs": [],
        }
    )
    assert doc["import_tariffs"]["monthly_import"]["type"] == "monthly_table"
    assert len(doc["import_tariffs"]["monthly_import"]["monthly_rates"]) == 1


def test_awattar_tariff_spec_includes_surcharges():
    root = Path(__file__).resolve().parents[1]
    doc = load_tariffs_document(str(root / "config" / "tariffs.json"))
    awattar = doc["import_tariffs"]["awattar_at"]
    assert awattar["fix_aufschlag_cent"] == pytest.approx(1.5)
    assert awattar["netzverlust_faktor"] == pytest.approx(1.03)
    dynamic = doc["export_tariffs"]["dynamic_epex"]
    assert dynamic["feed_in_fee_factor"] == pytest.approx(0.19)


def test_export_tariff_id_alias_awattar_sunny_float():
    from house_config.tariffs_store import resolve_export_tariff_into_settings

    tariffs = {
        "export_tariffs": {
            "dynamic_epex": {
                "id": "dynamic_epex",
                "label": "aWATTar SUNNY SPOT",
                "type": "dynamic_epex",
            }
        }
    }
    resolved = resolve_export_tariff_into_settings(
        {"export_tariff_id": "awattar_sunny_float"},
        tariffs,
    )
    assert resolved["feed_in_mode"] == "dynamic_epex"
    assert resolved["_export_tariff_spec"]["id"] == "dynamic_epex"


def test_tariff_spec_resolution_de_spot_ch_fix():
    resolved = config.CONFIG.resolve_scenario_settings_dict(
        {
            "import_tariff_id": "de_spot_test",
            "export_tariff_id": "ch_fix_test",
        }
    )
    assert resolved["market_zone"] == "DE-LU"
    assert resolved["_import_tariff_spec"]["type"] == "spot_hourly"
    assert resolved["_export_tariff_spec"]["type"] == "fixed"
    assert resolved["_export_tariff_spec"]["land"] == "CH"


def test_tariff_netzentgelt_override_resolution():
    resolved = config.CONFIG.resolve_scenario_settings_dict(
        {
            "import_tariff_id": "de_spot_test",
            "netzentgelt_cent_kwh_override": 8.0,
        }
    )
    assert resolved["netzentgelt_cent_kwh"] == 8.0


def test_monthly_float_export_tariff_resolution():
    root = Path(__file__).resolve().parents[1]
    doc = load_tariffs_document(str(root / "config" / "tariffs.json"))
    oemag = doc["export_tariffs"].get("at_oemag_gesetzlicher_marktpreis")
    assert oemag is not None
    assert oemag["type"] == "monthly_float"
    assert oemag["arbeitspreis_kwh_cent"] == pytest.approx(7.15)


def test_ev_consumer_normalization(tmp_path):
    import json

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
                                "id": "ev",
                                "type": "ev",
                                "nominal_power_kw": 3.5,
                                "min_power_kw": 1.4,
                                "min_on_quarterhours": 4,
                                "battery_capacity_kwh": 60.0,
                                "charging_schedule": _sample_ev_consumer()["charging_schedule"],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doc = load_house_profiles_document(str(path))
    ev = doc["profiles"]["home"]["consumers"][0]
    assert ev["type"] == "ev"
    assert ev["battery_capacity_kwh"] == 60.0
    assert "loxone" not in ev.get("charging_schedule", {})


def test_ev_annual_kwh_from_charging_schedule():
    consumer = _sample_ev_consumer()
    annual = estimate_ev_annual_kwh(consumer)
    assert annual > 5000.0
    assert consumer_annual_kwh(consumer) == annual


def test_ev_hourly_profile_only_in_charging_window():
    consumer = _sample_ev_consumer()
    weekday = date(2023, 6, 7)
    hourly = ev_hourly_kw_for_day(consumer, weekday)
    day_sched = consumer["charging_schedule"]["weekday"]
    from_h = int(day_sched["car_available_from_hour"])
    ready_h = int(day_sched["ready_by_hour"])
    for hour, kw in enumerate(hourly):
        if hour_in_charging_window(hour, from_h, ready_h):
            assert kw >= 0.0
        else:
            assert kw == 0.0
    assert sum(hourly) > 0.0


def test_build_hourly_kw_profile_with_ev_consumer(tmp_path):
    import json

    path = tmp_path / "house_profiles.json"
    ev = _sample_ev_consumer()
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "home",
                        "annual_kwh": 15000,
                        "consumers": [
                            {
                                "id": "ev",
                                "type": "ev",
                                "nominal_power_kw": 3.5,
                                "min_power_kw": 1.4,
                                "min_on_quarterhours": 4,
                                "battery_capacity_kwh": 60.0,
                                "charging_schedule": ev["charging_schedule"],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doc = load_house_profiles_document(str(path))
    profile = doc["profiles"]["home"]
    hourly = build_hourly_kw_profile(profile, hours=168)
    assert len(hourly) == 168
    assert max(hourly) > 0.0
    assert compute_baseload_kwh(profile["annual_kwh"], profile["consumers"])["consumer_kwh"] > 0


def _sample_generic_consumer(**overrides) -> dict:
    base = {
        "id": "washer",
        "label": "Waschmaschine",
        "type": "generic",
        "nominal_power_kw": 1.0,
        "schedule": {
            "runs_per_week": 2,
            "duration_h": 2.0,
            "start_hour": 18,
            "start_shift_h": 0.0,
        },
    }
    base.update(overrides)
    return base


def test_generic_annual_kwh_from_schedule():
    from house_config.generic_schedule import generic_annual_kwh

    consumer = _sample_generic_consumer()
    assert generic_annual_kwh(consumer) == pytest.approx(1.0 * 2.0 * 2 * 52)


def test_eligible_start_hours_shift_cases():
    from house_config.generic_schedule import eligible_start_hours

    assert eligible_start_hours(18, 0.0) == frozenset({18})
    assert eligible_start_hours(18, 2.0) == frozenset({16, 17, 18, 19, 20})
    assert len(eligible_start_hours(18, 12.0)) == 24


def test_migrate_start_flexibility_legacy():
    from house_config.generic_schedule import migrate_start_flexibility

    assert migrate_start_flexibility({"start_flexibility": "fixed"})["start_shift_h"] == 0.0
    assert migrate_start_flexibility({"start_flexibility": "day"})["start_shift_h"] == 12.0


def test_normalize_generic_schedule_migration(tmp_path):
    import json

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
                                "id": "washer",
                                "type": "generic",
                                "nominal_power_kw": 1.0,
                                "annual_kwh": 208.0,
                                "schedule": {
                                    "runs_per_week": 2,
                                    "start_flexibility": "day",
                                },
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doc = load_house_profiles_document(str(path))
    washer = doc["profiles"]["home"]["consumers"][0]
    assert washer["schedule"]["start_shift_h"] == 12.0
    assert washer["schedule"]["duration_h"] == pytest.approx(2.0)
    assert washer["annual_kwh"] == pytest.approx(208.0)


def test_generic_hourly_profile_fixed_start():
    from datetime import date

    from house_config.generic_schedule import generic_hourly_kw_for_day

    consumer = _sample_generic_consumer()
    monday = date(2023, 6, 5)
    hourly = generic_hourly_kw_for_day(consumer, monday)
    assert hourly[18] == pytest.approx(1.0)
    assert hourly[19] == pytest.approx(1.0)
    assert sum(hourly) == pytest.approx(2.0)


def test_build_hourly_kw_profile_generic_blocks(tmp_path):
    import json

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
                                "id": "washer",
                                "type": "generic",
                                "nominal_power_kw": 1.0,
                                "schedule": {
                                    "runs_per_week": 2,
                                    "duration_h": 2.0,
                                    "start_hour": 10,
                                    "start_shift_h": 0.0,
                                },
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doc = load_house_profiles_document(str(path))
    profile = doc["profiles"]["home"]
    hourly = build_hourly_kw_profile(profile, hours=168)
    assert max(hourly) >= 1.0
    assert sum(hourly) > 0.0


def test_planning_flex_bridge_split():
    from house_config.planning_flex_bridge import split_planning_generic_consumers

    profile = {
        "consumers": [
            _sample_generic_consumer(),
            _sample_generic_consumer(
                id="dryer",
                schedule={
                    "runs_per_week": 3,
                    "duration_h": 1.5,
                    "start_hour": 12,
                    "start_shift_h": 4.0,
                },
            ),
        ]
    }
    fixed, flex = split_planning_generic_consumers(profile)
    assert len(fixed) == 1
    assert len(flex) == 1
    assert flex[0]["generic_flex_window"]["start_shift_h"] == 4.0


def test_generic_flex_allowed_hours():
    from house_config.generic_schedule import generic_allowed_slot_hours

    allowed = generic_allowed_slot_hours(18, 2.0, 2.0)
    assert 16 in allowed
    assert 19 in allowed
    assert 21 in allowed
    assert 15 not in allowed
    assert 22 not in allowed


def test_scenario_resolution_includes_planning_flex(tmp_path):
    import json

    from house_config.scenario_resolution import resolve_scenario_settings

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
                                "id": "washer",
                                "type": "generic",
                                "nominal_power_kw": 1.0,
                                "schedule": {
                                    "runs_per_week": 2,
                                    "duration_h": 2.0,
                                    "start_hour": 12,
                                    "start_shift_h": 6.0,
                                },
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    resolved = resolve_scenario_settings(
        {"house_profile_id": "home"},
        raw_config=config.CONFIG._raw_config,
        tariffs_path=config.TARIFFS_JSON_PATH,
        house_profiles_path=str(path),
    )
    assert resolved.get("_house_profile") is not None
    flex = resolved.get("_planning_flex_consumers") or []
    assert any(item["id"] == "washer" for item in flex)


def test_runtime_baseline_resolves_entity_refs(tmp_path, monkeypatch):
    from house_config.scenario_resolution import resolve_runtime_settings_for_backtesting

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_TARIFFS_PATH", str(config_dir / "tariffs.json"))

    (config_dir / "config.json").write_text(
        """
        {
            "system": {"global_timeout": 10, "loop_timeout": 900},
            "loxone_blocks": {"soc_name": "Battery_SOC"},
            "file_paths_battery_simulation": {"path_cons_data": "runtime/cons_data_hourly.csv"},
            "planning_horizon": {"mode": "sunset_window"},
            "runtime_settings": {
                "battery_id": "home_5kwh",
                "pv_system_id": "roof",
                "import_tariff_id": "fixed_imp",
                "export_tariff_id": "fixed_exp",
                "house_profile_id": "efh"
            },
            "batteries": [{
                "id": "home_5kwh",
                "label": "5 kWh",
                "battery_capacity_kwh": 5.0,
                "battery_max_power_kw": 2.5,
                "battery_efficiency": 0.97,
                "battery_min_soc": 10.0,
                "battery_max_soc": 100.0,
                "threshold_power": 0.05,
                "battery_wear": {"enabled": false}
            }],
            "pv_systems": [{
                "id": "roof",
                "label": "Dach",
                "kwp": 10.0,
                "pv_tilt": 30,
                "pv_azimuth": 180
            }],
            "flexible_consumers": []
        }
        """.strip(),
        encoding="utf-8",
    )
    (config_dir / "house_profiles.json").write_text(
        """
        {
            "profiles": [{
                "id": "efh",
                "label": "EFH",
                "annual_kwh": 4000,
                "latitude": 48.2,
                "longitude": 11.0,
                "consumers": [{"id": "heat", "type": "thermal_annual", "nominal_power_kw": 3.0}]
            }]
        }
        """.strip(),
        encoding="utf-8",
    )
    (config_dir / "tariffs.json").write_text(
        """
        {
            "import_tariffs": [{"id": "fixed_imp", "label": "Fix", "type": "fixed_cent", "fix_cent_kwh": 37}],
            "export_tariffs": [{"id": "fixed_exp", "label": "Fix", "type": "fixed", "k_push_cent": 3.7}]
        }
        """.strip(),
        encoding="utf-8",
    )

    import json

    raw = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
    resolved = resolve_runtime_settings_for_backtesting(
        raw,
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
    )
    assert resolved["battery_capacity_kwh"] == 5.0
    assert resolved["pv_kwp"] == 10.0
    assert resolved["feed_in_mode"] == "fixed"
    assert resolved.get("_house_profile") is not None
    assert resolved["latitude"] == pytest.approx(48.2)
    assert resolved["timezone_name"] == "Europe/Berlin"


def test_migrate_runtime_entities_legacy_flat_to_ids(tmp_path):
    from house_config.migrate_runtime_entities import (
        RUNTIME_ID_KEYS,
        migrate_runtime_entities,
    )

    config = {
        "battery_wear": {
            "enabled": True,
            "replacement_cost_euro": 1500,
            "expected_cycles": 6000,
            "cycle_cost_fraction": 0.5,
        },
        "runtime_settings": {
            "k_push_cent": 3.5,
            "feed_in_mode": "fixed",
            "pv_tilt": 18,
            "pv_azimuth": 28,
            "pv_kwp": 6.0,
            "battery_max_power_kw": 4.0,
            "battery_efficiency": 0.95,
            "battery_capacity_kwh": 8.0,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "threshold_power": 0.02,
            "latitude": 47.404,
            "longitude": 9.743,
            "timezone_name": "Europe/Vienna",
        },
        "batteries": [],
        "pv_systems": [],
    }
    tariffs = {
        "import_tariffs": [
            {
                "id": "awattar_at",
                "label": "aWATTar",
                "type": "awattar",
                "land": "AT",
                "fix_aufschlag_cent": 1.5,
                "netzverlust_faktor": 1.03,
                "mwst_austria_faktor": 1.2,
            }
        ],
        "export_tariffs": [
            {"id": "fixed_35ct", "label": "Fix", "type": "fixed", "k_push_cent": 3.5}
        ],
    }
    profiles = {"profiles": []}

    migrated_config, migrated_tariffs, migrated_profiles, notes = migrate_runtime_entities(
        config,
        tariffs_doc=tariffs,
        house_profiles_doc=profiles,
    )
    runtime = migrated_config["runtime_settings"]
    assert set(runtime) <= RUNTIME_ID_KEYS
    assert runtime["pv_system_id"].startswith("pv_")
    assert runtime["import_tariff_id"] == "awattar_at"
    assert runtime["export_tariff_id"] == "fixed_35ct"
    assert runtime["house_profile_id"] == "migrated_home"
    assert any("battery_wear" in note for note in notes)
    assert migrated_profiles["profiles"][0]["latitude"] == pytest.approx(47.404)
    assert migrated_profiles["profiles"][0]["timezone_name"] == "Europe/Vienna"


def test_migrate_runtime_entities_preserves_resolved_values(tmp_path):
    from house_config.migrate_runtime_entities import (
        effective_runtime_values,
        migrate_runtime_entities,
    )

    repo = Path(__file__).resolve().parents[1]
    config = json.loads(
        (repo / "tests/fixtures/backtesting/config.json").read_text(encoding="utf-8")
    )
    tariffs = json.loads(
        (repo / "tests/fixtures/backtesting/tariffs.json").read_text(encoding="utf-8")
    )
    profiles = json.loads(
        (repo / "tests/fixtures/backtesting/house_profiles.json").read_text(encoding="utf-8")
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (config_dir / "tariffs.json").write_text(json.dumps(tariffs), encoding="utf-8")
    (config_dir / "house_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")

    before = effective_runtime_values(
        config,
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
    )
    migrated_config, _, migrated_profiles, _ = migrate_runtime_entities(
        config,
        tariffs_doc=tariffs,
        house_profiles_doc=profiles,
    )
    out_dir = tmp_path / "migrated"
    out_dir.mkdir()
    (out_dir / "config.json").write_text(json.dumps(migrated_config), encoding="utf-8")
    (out_dir / "tariffs.json").write_text(json.dumps(tariffs), encoding="utf-8")
    (out_dir / "house_profiles.json").write_text(
        json.dumps(migrated_profiles), encoding="utf-8"
    )

    after = effective_runtime_values(
        migrated_config,
        tariffs_path=str(out_dir / "tariffs.json"),
        house_profiles_path=str(out_dir / "house_profiles.json"),
    )
    for key in before:
        if before[key] is None and after[key] is None:
            continue
        assert after[key] == pytest.approx(before[key], rel=1e-4, abs=1e-4), key


def test_migrate_runtime_entities_cli_writes_draft(tmp_path):
    from scripts.migrate_runtime_entities import main

    repo = Path(__file__).resolve().parents[1]
    config_dir = repo / "tests/fixtures/backtesting"
    out_dir = tmp_path / "draft"
    assert main(
        [
            "--input",
            str(config_dir / "config.json"),
            "--tariffs",
            str(config_dir / "tariffs.json"),
            "--house-profiles",
            str(config_dir / "house_profiles.json"),
            "--output-dir",
            str(out_dir),
        ]
    ) == 0
    assert (out_dir / "config.json").is_file()
    assert (out_dir / "MIGRATION_REVIEW.md").is_file()
    runtime = json.loads((out_dir / "config.json").read_text(encoding="utf-8"))[
        "runtime_settings"
    ]
    assert "battery_id" in runtime
    assert "pv_kwp" not in runtime

