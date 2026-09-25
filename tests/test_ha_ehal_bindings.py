"""Tests for 2.6.g HA Pattern B migrate / aggregate."""
from __future__ import annotations

from house_config.ehal_bindings import ensure_migrated, strip_migrated_config_keys
from house_config.ha_ehal_bindings import (
    aggregate_ha_entities,
    apply_ha_entities_to_house,
    migrate_ha_entities_to_house,
)
from house_sim.archetype import load_archetype


def _golden_entities() -> dict[str, str]:
    package = load_archetype("evcc_en")
    return dict(package.ehal_entities)


def test_migrate_ha_entities_to_plant_without_ev_consumer():
    entities = _golden_entities()
    house, changed = migrate_ha_entities_to_house({}, entities)
    assert changed
    plant = house["plant"]["ehal_bindings"]
    assert plant["sens_ess_soc"] == entities["sens_ess_soc"]
    assert plant["sens_evcs_active_power"] == entities["sens_evcs_active_power"]
    assert plant["set_evcs_max_current"] == entities["set_evcs_max_current"]
    assert aggregate_ha_entities(house) == {
        k: v for k, v in entities.items() if v
    }


def test_migrate_ha_entities_ev_to_consumer():
    entities = {
        "sens_grid_power_active": "sensor.grid",
        "sens_pv_production_active": "sensor.pv",
        "sens_ess_soc": "sensor.soc",
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
    assert plant["sens_ess_soc"] == "sensor.soc"
    assert "sens_evcs_active_power" not in plant
    ev = house["profiles"]["live"]["consumers"][0]["ehal_bindings"]
    assert ev["sens_evcs_active_power"] == "sensor.ev_power"
    assert ev["set_evcs_max_current"] == "number.ev_amps"
    assert aggregate_ha_entities(house)["sens_evcs_active_power"] == "sensor.ev_power"


def test_migrate_empty_only_does_not_overwrite():
    house = {
        "plant": {"ehal_bindings": {"sens_ess_soc": "sensor.keep"}},
        "profiles": {},
    }
    house, changed = migrate_ha_entities_to_house(
        house, {"sens_ess_soc": "sensor.other", "sens_grid_power_active": "sensor.grid"}
    )
    assert changed
    assert house["plant"]["ehal_bindings"]["sens_ess_soc"] == "sensor.keep"
    assert house["plant"]["ehal_bindings"]["sens_grid_power_active"] == "sensor.grid"


def test_ensure_migrated_strips_ha_entities(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_DOTENV_PATH", str(tmp_path / ".env"))
    entities = _golden_entities()
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
    assert aggregate_ha_entities(house)["sens_ess_soc"] == entities["sens_ess_soc"]
    assert config_out["ehal"]["ha"]["entities"] == {}
    assert config_out["ehal"]["ha"]["sign"]["sens_grid_power_active"] == "ehal"
    assert "base_url" not in config_out["ehal"]["ha"]
    assert "token" not in config_out["ehal"]["ha"]
    stripped = strip_migrated_config_keys(config)
    assert stripped["ehal"]["ha"]["entities"] == {}
    assert "base_url" not in stripped["ehal"]["ha"]


def test_apply_ha_entities_overwrites_and_clears():
    house = {
        "plant": {
            "ehal_bindings": {
                "sens_ess_soc": "sensor.old",
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
            "sens_ess_soc": "sensor.new",
            "sens_evcs_active_power": "sensor.ev",
        },
    )
    plant = updated["plant"]["ehal_bindings"]
    assert plant["sens_ess_soc"] == "sensor.new"
    assert plant["sens_temperature_outside"] == "sensor.outside"
    assert "sens_evcs_active_power" not in plant
    assert (
        updated["profiles"]["live"]["consumers"][0]["ehal_bindings"][
            "sens_evcs_active_power"
        ]
        == "sensor.ev"
    )


def test_aggregate_empty_house():
    assert aggregate_ha_entities(None) == {}
    assert aggregate_ha_entities({}) == {}


def test_get_ha_adapter_prefers_house_bindings(monkeypatch, tmp_path):
    from integrations import ehal_live

    entities = {
        "sens_grid_power_active": "sensor.grid",
        "sens_pv_production_active": "sensor.pv",
        "sens_ess_soc": "sensor.soc",
    }
    house = {
        "plant": {"ehal_bindings": entities},
        "profiles": {},
    }
    monkeypatch.setattr(
        "house_config.ha_ehal_bindings.load_house_profiles_for_ha",
        lambda: house,
    )
    monkeypatch.setattr(
        ehal_live.config,
        "get",
        lambda key, default=None: {
            "EHAL_HA_BASE_URL": "http://127.0.0.1:9",
            "EHAL_HA_TOKEN": "token",
            "EHAL_ADAPTER_ID": "earnie-hems",
            "EHAL_HA_ENTITIES": {"sens_ess_soc": "sensor.legacy"},
            "EHAL_HA_SIGN": {},
            "GLOBAL_TIMEOUT": 5,
        }.get(key, default),
    )
    ehal_live.reset_adapter_cache()
    adapter = ehal_live.get_ha_adapter()
    assert adapter.cfg.entities["sens_ess_soc"] == "sensor.soc"
    assert adapter.cfg.entities["sens_grid_power_active"] == "sensor.grid"
    ehal_live.reset_adapter_cache()


def test_get_ha_adapter_legacy_fallback_when_house_empty(monkeypatch):
    from integrations import ehal_live

    monkeypatch.setattr(
        "house_config.ha_ehal_bindings.load_house_profiles_for_ha",
        lambda: {"plant": {"ehal_bindings": {}}},
    )
    monkeypatch.setattr(
        ehal_live.config,
        "get",
        lambda key, default=None: {
            "EHAL_HA_BASE_URL": "http://127.0.0.1:9",
            "EHAL_HA_TOKEN": "token",
            "EHAL_ADAPTER_ID": "earnie-hems",
            "EHAL_HA_ENTITIES": {
                "sens_grid_power_active": "sensor.legacy_grid",
                "sens_pv_production_active": "sensor.legacy_pv",
                "sens_ess_soc": "sensor.legacy_soc",
            },
            "EHAL_HA_SIGN": {},
            "GLOBAL_TIMEOUT": 5,
        }.get(key, default),
    )
    ehal_live.reset_adapter_cache()
    adapter = ehal_live.get_ha_adapter()
    assert adapter.cfg.entities["sens_ess_soc"] == "sensor.legacy_soc"
    ehal_live.reset_adapter_cache()
