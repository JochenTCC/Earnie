"""dm5.house_thermal: building fields of thermal_annual → house profile (Heizung betrachten)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from runtime_store.migration.io_util import load_pack_docs
from runtime_store.migration.registry import STEPS
from runtime_store.migration.steps.house_thermal import apply, detect

FIXTURE = Path(__file__).parent / "fixtures" / "migration" / "v5_pre_house_thermal"
HOUSE = "house_profiles.json"


def _docs(*consumers: dict, **profile_fields) -> dict:
    return {
        HOUSE: {
            "earnie_data_model": 5,
            "profiles": [
                {"id": "home", "label": "Haus", "consumers": list(consumers), **profile_fields}
            ],
        }
    }


def _profile(docs: dict) -> dict:
    return docs[HOUSE]["profiles"][0]


def test_building_fields_move_to_the_house_and_the_switch_turns_on():
    docs = _docs(
        {
            "id": "wp",
            "type": "thermal_annual",
            "heating_system_id": "heating_home",
            "absent_mode_enabled": True,
            "living_area_m2": 150.0,
            "hwb_kwh_m2": 40.0,
            "building_class": 2,
            "building_mass": "leicht",
            "target_temp_c": 21.0,
            "heating_limit_c": 14.0,
            "house_tolerance_c": 0.8,
            "house_heat_loss_kw_per_k": 0.15,
            "absent_temp_reduction_c": 4.0,
            "persons": 3,
            "solar_thermal_area_m2": 6.0,
        }
    )
    assert detect(docs)
    result = apply(docs, {})
    assert not result.blockers
    assert result.changed_files == (HOUSE,)
    profile = _profile(result.docs)
    assert profile["heating_enabled"] is True
    assert profile["persons"] == 3
    assert profile["thermal"] == {
        "living_area_m2": 150.0,
        "hwb_kwh_m2": 40.0,
        "building_class": 2,
        "building_mass": "leicht",
        "target_temp_c": 21.0,
        "heating_limit_c": 14.0,
        "house_tolerance_c": 0.8,
        "house_heat_loss_kw_per_k": 0.15,
        "absent_temp_reduction_c": 4.0,
        "absent_mode_enabled": True,
    }
    # The collector is heat generation and stays with the consumer.
    assert profile["consumers"][0] == {
        "id": "wp",
        "type": "thermal_annual",
        "heating_system_id": "heating_home",
        "solar_thermal_area_m2": 6.0,
    }
    assert not detect(result.docs)


def test_house_without_heating_consumer_gets_the_switch_off():
    docs = _docs({"id": "herd", "type": "generic", "annual_kwh": 500.0})
    profile = _profile(apply(docs, {}).docs)
    assert profile["heating_enabled"] is False
    assert profile["persons"] == 2
    assert "thermal" not in profile


def test_old_loader_semantics_are_kept():
    """Missing fields stay missing; falsy ``or default`` fields, clamps and legacy setback."""
    docs = _docs(
        {
            "id": "wp",
            "type": "thermal_annual",
            "heating_system_id": "heating_home",
            "building_class": 0,
            "heating_limit_c": 0,
            "house_tolerance_c": 0.01,
            "target_temp_c": 22.0,
            "absent_temp_c": 18.5,
            "thermal": {"living_area_m2": 99.0, "solar_thermal_tilt_deg": 30.0},
        }
    )
    profile = _profile(apply(docs, {}).docs)
    assert profile["thermal"] == {
        "target_temp_c": 22.0,
        "house_tolerance_c": 0.05,
        "living_area_m2": 99.0,
        "absent_temp_reduction_c": 3.5,
        "absent_mode_enabled": False,
    }
    assert profile["consumers"][0]["thermal"] == {"solar_thermal_tilt_deg": 30.0}


def test_two_heating_consumers_block():
    docs = _docs(
        {"id": "a", "type": "thermal_annual", "heating_system_id": "x"},
        {"id": "b", "type": "thermal_annual", "heating_system_id": "y"},
    )
    result = apply(docs, {})
    assert result.blockers
    assert "mehrere Verbraucher" in result.blockers[0].message_de
    assert result.docs is docs


def test_step_runs_after_heating_systems():
    ids = [step.id for step in STEPS]
    assert ids.index("dm5.house_thermal") == ids.index("dm5.heating_systems") + 1


def test_fixture_migrates_and_loads_with_the_same_building_values(tmp_path):
    from house_config.components_store import clear_components_doc_cache
    from house_config.profiles_store import (
        clear_house_profiles_doc_cache,
        load_house_profiles_document,
    )

    config_dir = tmp_path / "pack"
    shutil.copytree(FIXTURE, config_dir)
    docs = load_pack_docs(config_dir)
    assert detect(docs)
    result = apply(docs, {})
    assert not result.blockers
    (config_dir / HOUSE).write_text(json.dumps(result.docs[HOUSE]), encoding="utf-8")
    from runtime_store.migration.steps.heating_power import apply as apply_heating_power

    components = apply_heating_power(result.docs, {}).docs["components.json"]
    # The gas variant has nominal_power_kw 0: no heating power to derive, the user enters it.
    for entry in components["heating_systems"]:
        entry.setdefault("heating_power_kw", 9.0)
    # The loader reads data model 6: the EV of the fixture needs its wallbox (dm6.wallboxes).
    from runtime_store.migration.steps.wallboxes import apply as apply_wallboxes

    dm6 = apply_wallboxes({HOUSE: result.docs[HOUSE], "components.json": components}, {}).docs
    components = dm6["components.json"]
    (config_dir / HOUSE).write_text(json.dumps(dm6[HOUSE]), encoding="utf-8")
    (config_dir / "components.json").write_text(json.dumps(components), encoding="utf-8")
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()
    profiles = load_house_profiles_document(str(config_dir / HOUSE))["profiles"]

    wp_a = next(c for c in profiles["profile_a"]["consumers"] if c["type"] == "thermal_annual")
    thermal = wp_a["thermal"]
    assert thermal["living_area_m2"] == 157.0
    assert thermal["hwb_kwh_m2"] == 40.0
    assert thermal["building_class"] == 2
    assert thermal["building_mass"] == "leicht"
    assert thermal["absent_temp_reduction_c"] == 6.5
    assert thermal["persons"] == 2
    assert thermal["solar_thermal_area_m2"] == 10.3
    assert wp_a["absent_mode_enabled"] is True

    assert profiles["profile_b"]["heating_enabled"] is False
    assert all(c["type"] != "thermal_annual" for c in profiles["profile_b"]["consumers"])

    wp_c = next(c for c in profiles["profile_c"]["consumers"] if c["type"] == "thermal_annual")
    assert wp_c["thermal"]["absent_temp_reduction_c"] == 21.5 - 18.0
    assert wp_c["thermal"]["persons"] == 3
    assert wp_c["absent_mode_enabled"] is False
