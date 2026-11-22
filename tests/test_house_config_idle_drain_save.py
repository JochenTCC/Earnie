"""Hauskonfigurator keeps the battery's idle drain (Reserve P4) on save."""
from __future__ import annotations

import json

import pytest

from house_config.components_store import load_components_document, save_components_document
from ui.house_config_entities_io import upsert_battery
from ui.planning_battery_form import _battery_save_payload
from ui.planning_battery_state import _BATTERY_DIRECT_WIDGETS


def _inverter() -> dict:
    return {
        "id": "wr_main",
        "label": "Haupt-Wechselrichter",
        "type": "hybrid",
        "ac_connection": "grid_tied",
        "control": "full",
        "efficiency": 0.97,
    }


def _battery_spec(**extra) -> dict:
    spec = {
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
    spec.update(extra)
    return spec


@pytest.fixture
def components_path(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    components = cfg / "components.json"
    save_components_document(
        str(components),
        {"inverters": [_inverter()], "batteries": [], "pv_systems": []},
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


def _stored(components, battery_id: str) -> dict:
    doc = load_components_document(str(components))
    return next(b for b in doc["batteries"] if b["id"] == battery_id)


def test_a_saved_idle_drain_is_persisted(components_path):
    battery_id = upsert_battery(_battery_spec(idle_drain_kw=0.125), stable_id="")
    assert _stored(components_path, battery_id)["idle_drain_kw"] == pytest.approx(0.125)


def test_a_save_without_the_field_keeps_the_stored_drain(components_path):
    battery_id = upsert_battery(_battery_spec(idle_drain_kw=0.125), stable_id="")
    upsert_battery(_battery_spec(battery_min_soc=12.0), stable_id=battery_id)
    stored = _stored(components_path, battery_id)
    assert stored["battery_min_soc"] == pytest.approx(12.0)
    assert stored["idle_drain_kw"] == pytest.approx(0.125)


def test_zero_drain_is_not_written(components_path):
    battery_id = upsert_battery(_battery_spec(idle_drain_kw=0.125), stable_id="")
    upsert_battery(_battery_spec(idle_drain_kw=0.0), stable_id=battery_id)
    assert "idle_drain_kw" not in _stored(components_path, battery_id)


def test_the_form_payload_carries_the_drain():
    fields = {
        "label": "Hausspeicher",
        "capacity": 15.0,
        "max_charge": 5.0,
        "max_discharge": 5.0,
        "efficiency": 0.97,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "threshold_percent": 5.0,
        "standby_power": 0.026,
        "idle_drain": 0.125,
        "battery_wear": {"enabled": False},
    }
    assert _battery_save_payload(fields)["idle_drain_kw"] == pytest.approx(0.125)


def test_the_drain_widget_is_seeded_from_the_session_values():
    assert ("planning_battery_idle_drain", "idle_drain") in _BATTERY_DIRECT_WIDGETS
