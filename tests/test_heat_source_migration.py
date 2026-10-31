"""dm5.heat_source: flat heat_pump_type → heat_source object (SUSI P1)."""
from __future__ import annotations

import copy

from runtime_store.migration.steps.heat_source import STEP, apply, detect


def _house(*consumers: dict) -> dict:
    return {
        "house_profiles.json": {
            "earnie_data_model": 5,
            "profiles": [{"id": "home", "consumers": list(consumers)}],
        }
    }


def _consumer(docs: dict) -> dict:
    return docs["house_profiles.json"]["profiles"][0]["consumers"][0]


def test_heat_pump_type_moves_into_heat_source():
    docs = _house({"id": "wp", "type": "thermal_annual", "heat_pump_type": "erde"})
    assert detect(docs)
    result = apply(docs, {})
    assert not result.blockers
    assert result.changed_files == ("house_profiles.json",)
    consumer = _consumer(result.docs)
    assert consumer["heat_source"] == {"type": "heat_pump", "heat_pump_type": "erde"}
    assert "heat_pump_type" not in consumer
    assert not detect(result.docs)


def test_missing_heat_pump_type_is_the_old_luft_default():
    result = apply(_house({"id": "wp", "type": "thermal_annual"}), {})
    assert _consumer(result.docs)["heat_source"] == {
        "type": "heat_pump",
        "heat_pump_type": "luft",
    }


def test_unknown_heat_pump_type_blocks_instead_of_guessing():
    docs = _house({"id": "wp", "type": "thermal_annual", "heat_pump_type": "wasser"})
    before = copy.deepcopy(docs)
    result = apply(docs, {})
    assert result.blockers and result.blockers[0].step_id == STEP.id
    assert result.changed_files == ()
    assert docs == before


def test_already_migrated_and_other_consumers_untouched():
    docs = _house(
        {"id": "wp", "type": "thermal_annual", "heat_source": {"type": "gas"}},
        {"id": "ev", "type": "ev"},
    )
    assert not detect(docs)
    assert apply(docs, {}).changed_files == ()


def test_migrated_profile_loads(tmp_path):
    import json

    from house_config.profiles_store import load_house_profiles_document

    docs = _house(
        {
            "id": "wp",
            "type": "thermal_annual",
            "nominal_power_kw": 3.0,
            "living_area_m2": 120.0,
            "heat_pump_type": "erde",
        }
    )
    profile = docs["house_profiles.json"]["profiles"][0]
    profile.update(
        {
            "annual_kwh": 4000,
            "latitude": 47.0,
            "longitude": 10.0,
            "netznutzung": {"area_id": "user_no_grid_fee"},
        }
    )
    path = tmp_path / "house_profiles.json"
    path.write_text(json.dumps(apply(docs, {}).docs["house_profiles.json"]), encoding="utf-8")
    loaded = load_house_profiles_document(str(path))
    thermal = loaded["profiles"]["home"]["consumers"][0]["thermal"]
    assert thermal["heat_source"] == {"type": "heat_pump", "heat_pump_type": "erde"}
