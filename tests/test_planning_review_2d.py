"""Planning form fixes from the ui slice 2 review, package 2d (save paths, session state)."""
from __future__ import annotations

import pytest

from house_config.components_store import load_components_document
from tests.test_inverter_p2 import components_env  # noqa: F401 — fixture
from ui.house_config_entities_io import upsert_battery, upsert_inverter, upsert_pv_system

_HOUSE = {
    "label": "Haus 5 kWh",
    "battery_capacity_kwh": 5.0,
    "battery_max_charge_power_kw": 2.5,
    "battery_max_discharge_power_kw": 2.5,
    "battery_efficiency": 0.97,
    "battery_min_soc": 10.0,
    "battery_max_soc": 100.0,
    "inverter_id": "wr_main",
    "regulates_on": "grid",
    "battery_wear": {"enabled": False},
}

_PHYSICAL_PS = {
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


def _doc(env) -> dict:
    return load_components_document(str(env["components"]))


def _by_id(rows: list[dict], entity_id: str) -> dict:
    return next(row for row in rows if row["id"] == entity_id)


# --- 2d-2: house battery → Powerstation ------------------------------------------------


def test_stored_house_battery_switches_to_powerstation(components_env):
    bat_id = upsert_battery(dict(_HOUSE))
    # The form sends no regulates_on for a Powerstation; the stored one must not come back.
    switched = {key: value for key, value in _PHYSICAL_PS.items() if key != "label"}
    upsert_battery({"label": "Haus 5 kWh", **switched}, stable_id=bat_id)
    battery = _by_id(_doc(components_env)["batteries"], bat_id)
    assert battery["type"] == "powerstation"
    assert "regulates_on" not in battery


def test_virtual_powerstation_without_house_battery_is_refused_before_writing(components_env):
    """Reachable once 2d-2 lets the only house battery switch: reinit failed after the write."""
    bat_id = upsert_battery(dict(_HOUSE))
    before = components_env["components"].read_bytes()
    with pytest.raises(ValueError, match="Hausbatterie als Carve-out-Basis"):
        upsert_battery(
            {**_PHYSICAL_PS, "label": "Haus 5 kWh", "backing": "virtual"}, stable_id=bat_id
        )
    assert components_env["components"].read_bytes() == before


# --- 2d-4 / 2d-5: built-in inverter of a physical Powerstation ------------------------


def _physical_ps_with_limits(env) -> tuple[str, str]:
    bat_id = upsert_battery(dict(_PHYSICAL_PS))
    inv_id = _by_id(_doc(env)["batteries"], bat_id)["inverter_id"]
    stored = _by_id(_doc(env)["inverters"], inv_id)
    upsert_inverter({**stored, "max_ac_charge_kw": 0.8, "max_ac_power_kw": 1.8}, stable_id=inv_id)
    return bat_id, inv_id


def _form_payload(inv_id: str, bat_id: str) -> dict:
    """What render_builtin_inverter_section returns (no max_ac_charge_kw field)."""
    return {
        "id": inv_id,
        "label": "WR Eco",
        "type": "hybrid",
        "ac_connection": "island",
        "control": "full",
        "efficiency": 0.95,
        "owned_by": bat_id,
        "ehal_bindings": {},
    }


def test_builtin_inverter_save_keeps_the_charge_limit(components_env):
    """2d-5: the section's payload replaced the entry and dropped max_ac_charge_kw."""
    from ui.planning_battery_inverter import persist_builtin_inverter

    bat_id, inv_id = _physical_ps_with_limits(components_env)
    persist_builtin_inverter(_form_payload(inv_id, bat_id), battery_id=bat_id)
    inverter = _by_id(_doc(components_env)["inverters"], inv_id)
    assert inverter["max_ac_charge_kw"] == pytest.approx(0.8)
    assert inverter["efficiency"] == pytest.approx(0.95)


def test_renamed_powerstation_keeps_its_builtin_inverter(components_env, monkeypatch):
    """2d-4: the rename replaced wr_<old> by a default and the form save then failed."""
    import ui.house_config_battery_io as battery_io
    from ui.planning_battery_inverter import persist_builtin_inverter

    # No house profiles in this env; the consumer push on rename is not under test.
    monkeypatch.setattr(battery_io, "sync_consumers_from_powerstation_attached", lambda *a: None)

    bat_id, old_inv = _physical_ps_with_limits(components_env)
    upsert_pv_system(
        {
            "label": "Balkon",
            "kwp": 0.8,
            "pv_tilt": 30.0,
            "pv_azimuth": 0.0,
            "inverter_id": old_inv,
        }
    )
    new_bat = upsert_battery(
        {**_PHYSICAL_PS, "label": "Delta Garage"},
        stable_id=bat_id,
        force_id_from_label=True,
    )
    assert new_bat != bat_id
    doc = _doc(components_env)
    new_inv = _by_id(doc["batteries"], new_bat)["inverter_id"]
    assert new_inv != old_inv
    assert old_inv not in {inv["id"] for inv in doc["inverters"]}
    inverter = _by_id(doc["inverters"], new_inv)
    assert inverter["owned_by"] == new_bat
    assert inverter["max_ac_charge_kw"] == pytest.approx(0.8)
    assert inverter["max_ac_power_kw"] == pytest.approx(1.8)
    assert doc["pv_systems"][0]["inverter_id"] == new_inv
    # The form still holds the old inverter id; the save goes to the moved entry.
    persist_builtin_inverter(_form_payload(old_inv, new_bat), battery_id=new_bat)
    doc = _doc(components_env)
    assert _by_id(doc["inverters"], new_inv)["efficiency"] == pytest.approx(0.95)
    assert old_inv not in {inv["id"] for inv in doc["inverters"]}


def test_rename_moves_inverter_bindings():
    from house_config.inverter_lifecycle import rename_owned_island_inverter

    inverters = [
        {
            "id": "wr_eco",
            "owned_by": "delta",
            "ehal_bindings": {"inv.wr_eco.get_inv_ac_power": "sensor.eco_ac"},
        }
    ]
    moved, old = rename_owned_island_inverter(
        inverters, old_battery_id="eco", new_battery_id="delta"
    )
    assert old == "wr_eco"
    assert moved[0]["id"] == "wr_delta"
    assert moved[0]["ehal_bindings"] == {"inv.wr_delta.get_inv_ac_power": "sensor.eco_ac"}


# --- 2d-1 / 2d-3: session state of hidden widgets --------------------------------------


@pytest.fixture
def session(monkeypatch) -> dict:
    import streamlit as st

    state: dict = {}
    monkeypatch.setattr(st, "session_state", state)
    return state


def test_hidden_battery_widget_comes_back_with_its_last_value(session):
    from ui.planning_battery_state import (
        remember_battery_widgets,
        restore_hidden_battery_widgets,
    )

    key = "bat__planning_battery_wear_replacement_cost"
    session[key] = 2345.0
    remember_battery_widgets("bat")
    del session[key]  # Streamlit drops the key of a widget not rendered in a run
    restore_hidden_battery_widgets("bat")
    assert session[key] == 2345.0


def test_builtin_inverter_widgets_fill_only_missing_keys(session):
    from ui.planning_battery_inverter import seed_builtin_inverter_widgets

    session["bat__planning_bat_inv_label"] = "Eigene Eingabe"
    seed_builtin_inverter_widgets(
        "bat",
        {"id": "wr_bat", "label": "Powerstation-WR Bat", "efficiency": 0.97},
        only_missing=True,
    )
    assert session["bat__planning_bat_inv_label"] == "Eigene Eingabe"
    assert session["bat__planning_bat_inv_efficiency"] == pytest.approx(0.97)


# --- 2d-7: the editors watch the file their data is in ---------------------------------


@pytest.mark.parametrize(
    "module,func",
    [
        ("ui.planning_battery_state", "_config_file_stamp"),
        ("ui.planning_pv_form", "_config_file_stamp"),
        ("ui.planning_inverter_form", "_config_file_stamp"),
    ],
)
def test_editor_stamp_follows_components_json(components_env, module, func):
    import importlib

    stamp = getattr(importlib.import_module(module), func)()
    assert "components.json" in stamp


# --- 2d-8: fractional PV angles --------------------------------------------------------


def test_fractional_pv_angles_are_kept(session):
    from ui.planning_pv_form import _seed_pv_widget_state

    existing = {
        "id": "pv",
        "label": "Dach",
        "pv_kwp": 6.0,
        "pv_tilt": 17.5,
        "pv_azimuth": -12.5,
        "inverter_id": "wr_main",
    }
    _seed_pv_widget_state("pv", existing, profiles={}, default_profile={})
    assert session["pv__planning_pv_tilt"] == 17.5
    assert session["pv__planning_pv_azimuth"] == -12.5
