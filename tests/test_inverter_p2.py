"""Inverter P2: UI save path, owned island lifecycle, EcoFlow preset."""
from __future__ import annotations

import json

import pytest

from house_config.components_store import load_components_document, save_components_document
from house_config.inverter_lifecycle import (
    ensure_owned_island_inverter,
    inverter_refs_blocking_delete,
)
from house_config.inverter_presets import ecoflow_delta_3_seeds
from ui.house_config_entities_io import (
    delete_battery,
    delete_inverter,
    upsert_battery,
    upsert_inverter,
    upsert_pv_system,
)

_WR_MAIN = {
    "id": "wr_main",
    "label": "Haupt-Wechselrichter",
    "type": "hybrid",
    "ac_connection": "grid_tied",
    "control": "full",
}


@pytest.fixture
def components_env(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    components = cfg / "components.json"
    scenarios = cfg / "backtesting_scenarios.json"
    config_json = cfg / "config.json"
    save_components_document(
        str(components),
        {"inverters": [_WR_MAIN], "batteries": [], "pv_systems": []},
    )
    scenarios.write_text(
        json.dumps(
            {
                "earnie_data_model": 4,
                "scenarios": [
                    {
                        "id": "live",
                        "label": "Live",
                        "settings": {"battery_ids": [], "pv_system_ids": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config_json.write_text(
        json.dumps(
            {
                "live_scenario_id": "live",
                "system": {"global_timeout": 10, "loop_timeout": 900},
                "planning_horizon": {"mode": "sunrise_window"},
                "flexible_consumers": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(components))
    monkeypatch.setenv("EARNIE_BACKTESTING_SCENARIOS_PATH", str(scenarios))
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.delenv("EARNIE_ENV_PATH", raising=False)

    import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "reinit_config", lambda: None)
    return {"components": components}


def test_upsert_inverter_and_pv_battery_link(components_env):
    components = components_env["components"]
    bat_id = upsert_battery(
        {
            "label": "Haus 5 kWh",
            "battery_capacity_kwh": 5.0,
            "battery_max_charge_power_kw": 2.5,
            "battery_max_discharge_power_kw": 2.5,
            "battery_efficiency": 0.97,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "inverter_id": "wr_main",
            "battery_wear": {"enabled": False},
        }
    )
    pv_id = upsert_pv_system(
        {
            "label": "Dach Süd",
            "kwp": 6.0,
            "pv_tilt": 18.0,
            "pv_azimuth": 0.0,
            "inverter_id": "wr_main",
        }
    )
    doc = load_components_document(str(components))
    assert bat_id
    assert pv_id
    assert doc["batteries"][0]["inverter_id"] == "wr_main"
    assert doc["pv_systems"][0]["inverter_id"] == "wr_main"
    assert "kind" not in doc["batteries"][0]


def test_physical_powerstation_gets_owned_island(components_env):
    components = components_env["components"]
    bat_id = upsert_battery(
        {
            "label": "Eco Pack",
            "type": "powerstation",
            "backing": "physical",
            "role": "single_use",
            "battery_capacity_kwh": 1.0,
            "battery_max_charge_power_kw": 1.0,
            "battery_max_discharge_power_kw": 0.0,
            "battery_efficiency": 0.9,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "battery_wear": {"enabled": False},
        }
    )
    doc = load_components_document(str(components))
    bat = next(b for b in doc["batteries"] if b["id"] == bat_id)
    inv_id = bat["inverter_id"]
    inv = next(i for i in doc["inverters"] if i["id"] == inv_id)
    assert inv["ac_connection"] == "island"
    assert inv["owned_by"] == bat_id
    assert inv["type"] == "hybrid"


def test_virtual_powerstation_has_no_inverter(components_env):
    components = components_env["components"]
    upsert_battery(
        {
            "label": "Haus 10",
            "battery_capacity_kwh": 10.0,
            "battery_max_charge_power_kw": 5.0,
            "battery_max_discharge_power_kw": 5.0,
            "battery_efficiency": 0.95,
            "battery_min_soc": 5.0,
            "battery_max_soc": 100.0,
            "inverter_id": "wr_main",
            "battery_wear": {"enabled": False},
        }
    )
    ps_id = upsert_battery(
        {
            "label": "Virtuell Waschen",
            "type": "powerstation",
            "backing": "virtual",
            "role": "single_use",
            "battery_capacity_kwh": 1.5,
            "battery_wear": {"enabled": False},
        }
    )
    doc = load_components_document(str(components))
    ps = next(b for b in doc["batteries"] if b["id"] == ps_id)
    assert "inverter_id" not in ps


def test_delete_battery_removes_owned_inverter(components_env):
    components = components_env["components"]
    bat_id = upsert_battery(
        {
            "label": "Pack",
            "type": "powerstation",
            "backing": "physical",
            "role": "single_use",
            "battery_capacity_kwh": 1.0,
            "battery_max_charge_power_kw": 1.0,
            "battery_max_discharge_power_kw": 0.0,
            "battery_efficiency": 0.9,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "battery_wear": {"enabled": False},
        }
    )
    doc = load_components_document(str(components))
    inv_id = next(b for b in doc["batteries"] if b["id"] == bat_id)["inverter_id"]
    delete_battery(bat_id)
    doc = load_components_document(str(components))
    assert bat_id not in {b["id"] for b in doc["batteries"]}
    assert inv_id not in {i["id"] for i in doc["inverters"]}


def test_delete_inverter_blocked_when_referenced(components_env):
    upsert_battery(
        {
            "label": "Haus",
            "battery_capacity_kwh": 5.0,
            "battery_max_charge_power_kw": 2.5,
            "battery_max_discharge_power_kw": 2.5,
            "battery_efficiency": 0.97,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "inverter_id": "wr_main",
            "battery_wear": {"enabled": False},
        }
    )
    with pytest.raises(ValueError, match="referenziert"):
        delete_inverter("wr_main")


def test_ecoflow_preset_seeds():
    bat, inv = ecoflow_delta_3_seeds()
    assert bat["type"] == "powerstation"
    assert bat["backing"] == "physical"
    assert bat["inverter_id"] == inv["id"]
    assert inv["owned_by"] == bat["id"]
    assert inv["ac_connection"] == "island"


def test_ensure_owned_island_and_refs_helper():
    invs, inv_id = ensure_owned_island_inverter(
        [], battery_id="pack_a", battery_label="Pack A"
    )
    assert inv_id == "wr_pack_a"
    assert invs[0]["owned_by"] == "pack_a"
    refs = inverter_refs_blocking_delete(
        inverter_id="wr_pack_a",
        batteries=[{"id": "pack_a", "inverter_id": "wr_pack_a"}],
        pv_systems=[{"id": "pv1", "inverter_id": "wr_pack_a"}],
        exclude_battery_id="pack_a",
    )
    assert refs == ["PV-Anlage 'pv1'"]


def test_upsert_inverter_entity_id_lock(components_env):
    components = components_env["components"]
    first = upsert_inverter(
        {
            "label": "WR Nord copy",
            "id_provisional_label": "WR Nord copy",
            "type": "hybrid",
            "ac_connection": "grid_tied",
            "control": "full",
        },
        stable_id="",
    )
    assert first == "wr_nord_copy"
    doc = load_components_document(str(components))
    inv = next(i for i in doc["inverters"] if i["id"] == first)
    assert inv["id_locked"] is False
    second = upsert_inverter(
        {
            "label": "Garage WR",
            "type": "hybrid",
            "ac_connection": "grid_tied",
            "control": "full",
        },
        stable_id=first,
    )
    assert second == "garage_wr"
    doc = load_components_document(str(components))
    inv = next(i for i in doc["inverters"] if i["id"] == second)
    assert inv["id_locked"] is True
