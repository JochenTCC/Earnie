"""dm5.heating_systems: inline heat generation → components.json heating_systems[]."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from runtime_store.migration.io_util import load_pack_docs
from runtime_store.migration.registry import STEPS
from runtime_store.migration.steps.heating_systems import STEP, apply, detect

FIXTURE = Path(__file__).parent / "fixtures" / "migration" / "v5_pre_heating_systems"


def _docs(*consumers: dict, catalog: list | None = None) -> dict:
    docs: dict = {
        "house_profiles.json": {
            "earnie_data_model": 5,
            "profiles": [{"id": "home", "label": "Haus", "consumers": list(consumers)}],
        },
        "components.json": {"earnie_data_model": 5, "inverters": [], "batteries": []},
    }
    if catalog is not None:
        docs["components.json"]["heating_systems"] = catalog
    return docs


def _consumer(docs: dict) -> dict:
    return docs["house_profiles.json"]["profiles"][0]["consumers"][0]


def test_generation_fields_move_into_a_reference_entry():
    storage = {"volume_liters": 300.0}
    rod = [{"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}]
    docs = _docs(
        {
            "id": "wp",
            "type": "thermal_annual",
            "living_area_m2": 120.0,
            "heat_source": {"type": "heat_pump", "heat_pump_type": "erde"},
            "nominal_power_kw": 2.5,
            "min_on_quarterhours": 4,
            "heat_storage": storage,
            "parts": rod,
        }
    )
    assert detect(docs)
    result = apply(docs, {})
    assert not result.blockers
    assert set(result.changed_files) == {"house_profiles.json", "components.json"}
    consumer = _consumer(result.docs)
    assert consumer == {
        "id": "wp",
        "type": "thermal_annual",
        "living_area_m2": 120.0,
        "heating_system_id": "heating_home",
    }
    assert result.docs["components.json"]["heating_systems"] == [
        {
            "id": "heating_home",
            "label": "Heizsystem Haus",
            "heat_source": {"type": "heat_pump", "heat_pump_type": "erde"},
            "nominal_power_kw": 2.5,
            "min_on_quarterhours": 4,
            "heat_storage": storage,
            "parts": rod,
        }
    ]
    assert not detect(result.docs)


def test_missing_fields_stay_missing():
    result = apply(_docs({"id": "wp", "type": "thermal_annual", "heat_source": {"type": "gas"}}), {})
    assert result.docs["components.json"]["heating_systems"] == [
        {"id": "heating_home", "label": "Heizsystem Haus", "heat_source": {"type": "gas"}}
    ]


def test_id_collision_gets_a_suffix():
    taken = [{"id": "heating_home", "heat_source": {"type": "gas"}}]
    result = apply(
        _docs({"id": "wp", "type": "thermal_annual", "heat_source": {"type": "oil"}}, catalog=taken),
        {},
    )
    assert _consumer(result.docs)["heating_system_id"] == "heating_home_2"
    assert [e["id"] for e in result.docs["components.json"]["heating_systems"]] == [
        "heating_home",
        "heating_home_2",
    ]


def test_missing_heat_source_blocks():
    docs = _docs({"id": "wp", "type": "thermal_annual"})
    before = copy.deepcopy(docs)
    result = apply(docs, {})
    assert result.blockers and result.blockers[0].step_id == STEP.id
    assert result.changed_files == ()
    assert docs == before


def test_already_migrated_untouched():
    docs = _docs(
        {"id": "wp", "type": "thermal_annual", "heating_system_id": "x"},
        {"id": "ev", "type": "ev"},
    )
    assert not detect(docs)


def test_runs_after_heat_source():
    ids = [step.id for step in STEPS]
    assert ids.index("dm5.heating_systems") == ids.index("dm5.heat_source") + 1


def test_dogfooding_fixture_migrates_and_loads(tmp_path):
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
    from runtime_store.migration.steps.house_thermal import apply as apply_house_thermal

    from runtime_store.migration.steps.heating_power import apply as apply_heating_power

    hoisted = apply_house_thermal(result.docs, {})
    powered = apply_heating_power(hoisted.docs, {})
    assert not powered.blockers
    # Gas entries with nominal_power_kw 0 get no heating power; the user enters it.
    for entry in powered.docs["components.json"]["heating_systems"]:
        if "heating_power_kw" not in entry:
            assert entry["heat_source"]["type"] == "gas"
            entry["heating_power_kw"] = 9.0
    for name in {*result.changed_files, *hoisted.changed_files, *powered.changed_files}:
        (config_dir / name).write_text(json.dumps(powered.docs[name]), encoding="utf-8")
    catalog = {e["id"]: e for e in result.docs["components.json"]["heating_systems"]}
    assert set(catalog) == {"heating_profile_a", "heating_profile_b", "heating_profile_b_2",
                            "heating_profile_c"}
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()
    profiles = load_house_profiles_document(str(config_dir / "house_profiles.json"))["profiles"]
    wp_a = next(c for c in profiles["profile_a"]["consumers"] if c["type"] == "thermal_annual")
    assert wp_a["heating_system_id"] == "heating_profile_a"
    assert wp_a["thermal"]["heat_source"] == {"type": "heat_pump", "heat_pump_type": "erde"}
    assert wp_a["thermal"]["heat_storage"]["volume_liters"] == 887.0
    assert wp_a["parts"][0]["id"] == "heating_rod"
    assert wp_a["nominal_power_kw"] == 1.9
    assert wp_a["min_on_quarterhours"] == 4
    wp_b = next(c for c in profiles["profile_b"]["consumers"] if c["type"] == "thermal_annual")
    assert wp_b["heating_system_id"] == "heating_profile_b_2"
    wp_c = next(c for c in profiles["profile_c"]["consumers"] if c["type"] == "thermal_annual")
    assert wp_c["thermal"]["heat_source"]["type"] == "gas"
    assert "heat_storage" not in wp_c["thermal"]
