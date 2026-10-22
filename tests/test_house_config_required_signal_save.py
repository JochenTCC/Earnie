"""Hauskonfigurator save activates ``ess.<id>.sens_ess_power`` for grid-tied house batteries (F14)."""
from __future__ import annotations

import json

import pytest

from ehal.ess_fields import ess_field
from house_config.components_store import load_components_document, save_components_document
from ui.house_config_entities_io import upsert_battery, upsert_inverter

_POWER = "sens_ess_power"


def _inverter(ac_connection: str) -> dict:
    return {
        "id": "wr_main",
        "label": "Haupt-Wechselrichter",
        "type": "hybrid",
        "ac_connection": ac_connection,
        "control": "full",
        "efficiency": 0.97,
    }


def _battery_spec() -> dict:
    return {
        "label": "Hausspeicher",
        "battery_capacity_kwh": 15.0,
        "battery_max_charge_power_kw": 5.0,
        "battery_max_discharge_power_kw": 5.0,
        "battery_efficiency": 0.97,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "inverter_id": "wr_main",
        "regulates_on": "grid",
        "battery_wear": {"enabled": False},
    }


@pytest.fixture
def components_path(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    components = cfg / "components.json"
    save_components_document(
        str(components),
        {"inverters": [_inverter("grid_tied")], "batteries": [], "pv_systems": []},
    )
    (cfg / "backtesting_scenarios.json").write_text(
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
    (cfg / "config.json").write_text(
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
    monkeypatch.setenv("EARNIE_BACKTESTING_SCENARIOS_PATH", str(cfg / "backtesting_scenarios.json"))
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.delenv("EARNIE_ENV_PATH", raising=False)
    import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "reinit_config", lambda: None)
    return components


def _bindings(components, battery_id: str) -> dict:
    doc = load_components_document(str(components))
    battery = next(b for b in doc["batteries"] if b["id"] == battery_id)
    return battery.get("ehal_bindings") or {}


def test_saving_a_grid_tied_house_battery_activates_sens_ess_power(components_path):
    battery_id = upsert_battery(_battery_spec(), stable_id="")
    assert ess_field(battery_id, _POWER) in _bindings(components_path, battery_id)


def test_saving_an_ac_connection_change_activates_it_on_the_existing_battery(components_path):
    battery_id = upsert_battery(_battery_spec(), stable_id="")
    doc = load_components_document(str(components_path))
    doc["inverters"] = [_inverter("island")]
    doc["batteries"][0]["ehal_bindings"].pop(ess_field(battery_id, _POWER), None)
    save_components_document(str(components_path), doc)
    assert ess_field(battery_id, _POWER) not in _bindings(components_path, battery_id)

    upsert_inverter(_inverter("grid_tied"), stable_id="wr_main")

    assert ess_field(battery_id, _POWER) in _bindings(components_path, battery_id)
