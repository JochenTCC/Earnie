"""Deferred id lock from Bezeichnung (batteries + PV)."""
from __future__ import annotations

import json

import pytest

from ehal.ess_fields import ess_field
from house_config.entity_id_lock import (
    resolve_id_on_save,
    rewrite_ess_bindings_slug,
)
from ui.house_config_entities_io import upsert_battery, upsert_pv_system


def test_resolve_new_unlocked_then_locks_on_label_change():
    taken: set[str] = set()
    eid, locked, provisional = resolve_id_on_save(
        label="15 kWh Speicher copy",
        stable_id="",
        existing=None,
        taken=taken,
        provisional_from_ui="15 kWh Speicher copy",
    )
    assert eid == "15_kwh_speicher_copy"
    assert locked is False
    assert provisional == "15 kWh Speicher copy"

    eid2, locked2, provisional2 = resolve_id_on_save(
        label="Garage West",
        stable_id=eid,
        existing={
            "id": eid,
            "id_locked": False,
            "id_provisional_label": provisional,
        },
        taken={eid},
    )
    assert eid2 == "garage_west"
    assert locked2 is True
    assert provisional2 == ""


def test_resolve_legacy_missing_flag_stays_locked():
    eid, locked, _ = resolve_id_on_save(
        label="Nice Name",
        stable_id="15_kwh_speicher_copy_3",
        existing={"id": "15_kwh_speicher_copy_3", "label": "Nice Name"},
        taken={"15_kwh_speicher_copy_3"},
    )
    assert eid == "15_kwh_speicher_copy_3"
    assert locked is True


def test_force_from_label_renames_locked():
    eid, locked, _ = resolve_id_on_save(
        label="Garage West",
        stable_id="15_kwh_speicher_copy_3",
        existing={"id": "15_kwh_speicher_copy_3", "id_locked": True},
        taken={"15_kwh_speicher_copy_3"},
        force_from_label=True,
    )
    assert eid == "garage_west"
    assert locked is True


def test_rewrite_ess_bindings_slug():
    old = "ugly_copy_3"
    new = "garage"
    bindings = {
        ess_field(old, "sens_ess_soc"): "sensor.soc",
        ess_field(old, "set_ess_mode"): "number.mode",
        "unrelated": "x",
    }
    out = rewrite_ess_bindings_slug(bindings, old_id=old, new_id=new)
    assert out[ess_field(new, "sens_ess_soc")] == "sensor.soc"
    assert out[ess_field(new, "set_ess_mode")] == "number.mode"
    assert out["unrelated"] == "x"
    assert ess_field(old, "sens_ess_soc") not in out


@pytest.fixture
def components_env(tmp_path, monkeypatch):
    """Minimal config tree for upsert_* via EARNIE_* path overrides."""
    from house_config.components_store import save_components_document

    cfg = tmp_path / "config"
    cfg.mkdir()
    components = cfg / "components.json"
    scenarios = cfg / "backtesting_scenarios.json"
    config_json = cfg / "config.json"
    save_components_document(
        str(components),
        {"batteries": [], "pv_systems": []},
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
    return {"components": components, "scenarios": scenarios}


def test_upsert_battery_locks_after_bezeichnung_change(components_env):
    from house_config.components_store import load_components_document
    from ui import house_config_io as io

    components = components_env["components"]
    first = upsert_battery(
        {
            "label": "15 kWh Speicher copy",
            "id_provisional_label": "15 kWh Speicher copy",
            "battery_capacity_kwh": 15.0,
            "battery_max_charge_power_kw": 5.0,
            "battery_max_discharge_power_kw": 5.0,
            "battery_efficiency": 0.97,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
            "ehal_bindings": {
                ess_field("15_kwh_speicher_copy", "sens_ess_soc"): "SoC",
            },
        },
        stable_id="",
    )
    assert first == "15_kwh_speicher_copy"
    doc = load_components_document(str(components))
    bat = doc["batteries"][0]
    assert bat["id_locked"] is False
    assert bat["id_provisional_label"] == "15 kWh Speicher copy"

    scen = io.load_backtesting_scenarios_raw()
    scen["scenarios"][0]["settings"]["battery_ids"] = [first]
    io.save_backtesting_scenarios(scen)

    second = upsert_battery(
        {
            "label": "Garage West",
            "battery_capacity_kwh": 15.0,
            "battery_max_charge_power_kw": 5.0,
            "battery_max_discharge_power_kw": 5.0,
            "battery_efficiency": 0.97,
            "battery_min_soc": 10.0,
            "battery_max_soc": 100.0,
        },
        stable_id=first,
    )
    assert second == "garage_west"
    doc = load_components_document(str(components))
    bat = doc["batteries"][0]
    assert bat["id"] == "garage_west"
    assert bat["id_locked"] is True
    assert "id_provisional_label" not in bat
    assert bat["ehal_bindings"][ess_field("garage_west", "sens_ess_soc")] == "SoC"
    scen = io.load_backtesting_scenarios_raw()
    assert scen["scenarios"][0]["settings"]["battery_ids"] == ["garage_west"]


def test_upsert_pv_locks_after_bezeichnung_change(components_env):
    from house_config.components_store import load_components_document
    from ui import house_config_io as io

    components = components_env["components"]
    first = upsert_pv_system(
        {
            "label": "Dach Süd copy",
            "id_provisional_label": "Dach Süd copy",
            "kwp": 10.0,
            "pv_tilt": 18.0,
            "pv_azimuth": 0.0,
        },
        stable_id="",
    )
    assert first == "dach_sued_copy"

    scen = io.load_backtesting_scenarios_raw()
    scen["scenarios"][0]["settings"]["pv_system_ids"] = [first]
    io.save_backtesting_scenarios(scen)

    second = upsert_pv_system(
        {
            "label": "Carport Ost",
            "kwp": 10.0,
            "pv_tilt": 18.0,
            "pv_azimuth": -90.0,
        },
        stable_id=first,
    )
    assert second == "carport_ost"
    doc = load_components_document(str(components))
    pv = doc["pv_systems"][0]
    assert pv["id"] == "carport_ost"
    assert pv["id_locked"] is True
    assert "id_provisional_label" not in pv
    scen = io.load_backtesting_scenarios_raw()
    assert scen["scenarios"][0]["settings"]["pv_system_ids"] == ["carport_ost"]
