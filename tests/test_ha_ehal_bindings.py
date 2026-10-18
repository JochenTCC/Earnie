"""Tests for HA entity-scoped migrate / aggregate (Binding P5e: empty activation)."""
from __future__ import annotations

from ehal.ess_fields import ess_field
from house_config.ehal_bindings import ensure_migrated, strip_migrated_config_keys
from house_config.ha_ehal_bindings import (
    aggregate_ha_entities,
    apply_ha_entities_to_house,
    migrate_ha_entities_to_house,
)
from house_sim.archetype import load_archetype


def test_migrate_ha_entities_to_plant_without_ev_consumer():
    entities = dict(load_archetype("evcc_en").ehal_entities)
    house, changed = migrate_ha_entities_to_house({}, entities)
    assert changed
    plant = house["plant"]["ehal_bindings"]
    assert plant["ess.house.sens_ess_soc"] == ""
    assert plant["sens_evcs_active_power"] == ""
    assert plant["set_evcs_max_current"] == ""
    aggregated = aggregate_ha_entities(house)
    assert aggregated["ess.house.sens_ess_soc"] == ""
    assert "sens_evcs_active_power" in aggregated


def test_migrate_ha_entities_ev_to_consumer():
    entities = {
        "sens_grid_power_active": "sensor.grid",
        "sens_pv_production_active": "sensor.pv",
        "ess.house.sens_ess_soc": "sensor.soc",
        "sens_evcs_active_power": "sensor.ev_power",
        "set_evcs_max_current": "number.ev_amps",
    }
    house = {
        "profiles": {
            "live": {
                "consumers": [{"id": "wallbox", "type": "ev", "ehal_bindings": {}}]
            }
        }
    }
    house, changed = migrate_ha_entities_to_house(house, entities)
    assert changed
    plant = house["plant"]["ehal_bindings"]
    assert plant["ess.house.sens_ess_soc"] == ""
    assert "sens_evcs_active_power" not in plant
    ev = house["profiles"]["live"]["consumers"][0]["ehal_bindings"]
    assert ev["sens_evcs_active_power"] == ""
    assert ev["set_evcs_max_current"] == ""
    assert aggregate_ha_entities(house)["sens_evcs_active_power"] == ""


def test_migrate_empty_only_does_not_overwrite_activation():
    house = {
        "plant": {"ehal_bindings": {"ess.house.sens_ess_soc": ""}},
        "profiles": {},
    }
    house, changed = migrate_ha_entities_to_house(
        house,
        {
            "ess.house.sens_ess_soc": "sensor.other",
            "sens_grid_power_active": "sensor.grid",
        },
    )
    assert changed
    assert house["plant"]["ehal_bindings"]["ess.house.sens_ess_soc"] == ""
    assert house["plant"]["ehal_bindings"]["sens_grid_power_active"] == ""


def test_ensure_migrated_strips_ha_entities(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_DOTENV_PATH", str(tmp_path / ".env"))
    entities = dict(load_archetype("evcc_en").ehal_entities)
    config = {
        "ehal": {
            "backend": "ha",
            "ha": {
                "base_url": "http://127.0.0.1:8124",
                "token": "t",
                "entities": entities,
                "sign": {"sens_grid_power_active": "ehal"},
            },
        }
    }
    house, config_out, changed = ensure_migrated({}, config)
    assert changed
    assert aggregate_ha_entities(house)["ess.house.sens_ess_soc"] == ""
    assert config_out["ehal"]["ha"]["entities"] == {}
    assert config_out["ehal"]["ha"]["sign"]["sens_grid_power_active"] == "ehal"
    assert "base_url" not in config_out["ehal"]["ha"]
    assert "token" not in config_out["ehal"]["ha"]
    stripped = strip_migrated_config_keys(config)
    assert stripped["ehal"]["ha"]["entities"] == {}
    assert "base_url" not in stripped["ehal"]["ha"]


def test_apply_ha_entities_activates_empty():
    house = {
        "plant": {
            "ehal_bindings": {
                "ess.house.sens_ess_soc": "sensor.old",
                "sens_temperature_outside": "sensor.outside",
            }
        },
        "profiles": {
            "live": {"consumers": [{"id": "ev1", "type": "ev", "ehal_bindings": {}}]}
        },
    }
    updated = apply_ha_entities_to_house(
        house,
        {
            "ess.house.sens_ess_soc": "sensor.new",
            "sens_evcs_active_power": "sensor.ev",
        },
    )
    plant = updated["plant"]["ehal_bindings"]
    assert plant["ess.house.sens_ess_soc"] == ""
    assert plant.get("sens_temperature_outside") == "sensor.outside"
    assert "sens_evcs_active_power" not in plant
    assert (
        updated["profiles"]["live"]["consumers"][0]["ehal_bindings"][
            "sens_evcs_active_power"
        ]
        == ""
    )


def test_aggregate_empty_house():
    empty_components = {"batteries": [], "inverters": [], "pv_systems": []}
    assert aggregate_ha_entities(None, components_doc=empty_components) == {}
    assert aggregate_ha_entities({}, components_doc=empty_components) == {}


def test_aggregate_two_batteries_entity_scoped():
    house = {
        "plant": {
            "ehal_bindings": {
                "sens_grid_power_active": "",
                "sens_pv_production_active": "",
            }
        },
        "profiles": {},
    }
    components = {
        "batteries": [
            {
                "id": "house",
                "ehal_bindings": {
                    ess_field("house", "sens_ess_soc"): "",
                    ess_field("house", "sens_ess_power"): "",
                },
            },
            {
                "id": "backup",
                "ehal_bindings": {
                    ess_field("backup", "sens_ess_soc"): "",
                },
            },
        ]
    }
    out = aggregate_ha_entities(house, components_doc=components)
    assert out[ess_field("house", "sens_ess_soc")] == ""
    assert out[ess_field("backup", "sens_ess_soc")] == ""
    assert out["sens_grid_power_active"] == ""
