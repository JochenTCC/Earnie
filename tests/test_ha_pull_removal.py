"""Binding P5e — migration dm4.ha_pull_removal."""
from __future__ import annotations

from runtime_store.migration.steps.ha_pull_removal import (
    STEP_ID,
    apply,
    detect,
    looks_like_ha_entity_id,
)


def test_looks_like_ha_entity_id():
    assert looks_like_ha_entity_id("sensor.grid") is True
    assert looks_like_ha_entity_id("number.charge") is True
    assert looks_like_ha_entity_id("Merker_SoC") is False
    assert looks_like_ha_entity_id("") is False


def test_detect_and_apply_clears_transport_and_entity_ids():
    docs = {
        "config.json": {
            "earnie_data_model": 4,
            "ehal": {"backend": "ha", "ha": {"transport": "pull", "sign": {}}},
        },
        "house_profiles.json": {
            "earnie_data_model": 4,
            "plant": {
                "ehal_bindings": {
                    "sens_grid_power_active": "sensor.grid",
                    "sens_pv_production_active": "",
                }
            },
            "profiles": {},
        },
        "components.json": {
            "earnie_data_model": 4,
            "batteries": [
                {
                    "id": "house",
                    "ehal_bindings": {"ess.house.sens_ess_soc": "sensor.soc"},
                }
            ],
        },
    }
    assert detect(docs) is True
    result = apply(docs, {})
    assert STEP_ID.startswith("dm4.")
    assert "config.json" in result.changed_files
    assert "transport" not in result.docs["config.json"]["ehal"]["ha"]
    house = result.docs["house_profiles.json"]
    assert house["plant"]["ehal_bindings"]["sens_grid_power_active"] == ""
    assert house["plant"]["ehal_bindings"]["sens_pv_production_active"] == ""
    bat = result.docs["components.json"]["batteries"][0]
    assert bat["ehal_bindings"]["ess.house.sens_ess_soc"] == ""
    assert detect(result.docs) is False
