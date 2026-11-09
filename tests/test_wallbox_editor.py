"""Wallbox editing (multi-EV M1b): Wallboxen tab store helpers and the EV save routing."""
from __future__ import annotations

import json

import pytest

from house_config.components_store import clear_components_doc_cache
from house_config.wallboxes import (
    WALLBOX_VOLTAGE_FORM_KEY,
    route_evs_to_wallboxes,
    wallboxes_by_id,
)
from tests.fixtures.ev_wallbox import ev_fields, wallbox_catalog, wallbox_entry


def _ev(wallbox_id: str = "wb_a", **currents) -> dict:
    return {
        "id": "e_auto",
        "label": "E-Auto",
        "type": "ev",
        "battery_capacity_kwh": 60.0,
        "charging_schedule": {
            "weekday": {"car_available_from_hour": 18, "ready_by_hour": 7, "daily_rest_soc": 40.0},
            "weekend": {"car_available_from_hour": 20, "ready_by_hour": 9, "daily_rest_soc": 30.0},
        },
        **ev_fields(wallbox_id, **currents),
    }


def _house(ev: dict) -> dict:
    return {
        "profiles": [
            {
                "id": "home",
                "label": "Home",
                "annual_kwh": 3000.0,
                "latitude": 48.2,
                "longitude": 11.0,
                "netznutzung": {"area_id": "user_no_grid_fee"},
                "consumers": [ev],
            }
        ]
    }


def test_saving_the_pair_view_keeps_the_wallbox_limits():
    """D2: car and wallbox limits differ; saving the loaded view must not copy one onto the other."""
    from house_config.profiles_store import normalize_house_profiles_document

    box = wallbox_entry("wb_a", phases=3, min_current_a=6.0, max_current_a=32.0)
    ev = _ev(phases=1, min_current_a=8.0, max_current_a=16.0)
    view = normalize_house_profiles_document(_house(ev), wallboxes=wallbox_catalog(box))
    profile = view["profiles"]["home"]
    assert profile["consumers"][0]["nominal_power_kw"] == pytest.approx(16 * 230 / 1000)

    (saved,), wallboxes = route_evs_to_wallboxes([profile], [box])

    limits = ("voltage_v", "phases", "min_current_a", "max_current_a")
    saved_box = wallboxes_by_id({"wallboxes": wallboxes})["wb_a"]
    assert {k: saved_box[k] for k in limits} == {k: box[k] for k in limits}
    stored_ev = saved["consumers"][0]
    assert (stored_ev["phases"], stored_ev["min_current_a"], stored_ev["max_current_a"]) == (
        1, 8.0, 16.0,
    )
    assert "nominal_power_kw" not in stored_ev


def test_import_voltage_creates_the_wallbox_with_the_pair_limits():
    """An importer's EV without assignment gets its own wallbox with the given voltage."""
    ev = _ev(phases=1, min_current_a=6.0, max_current_a=16.0)
    ev.pop("wallbox_assignment")
    ev[WALLBOX_VOLTAGE_FORM_KEY] = 230.0

    (saved,), wallboxes = route_evs_to_wallboxes([_house(ev)["profiles"][0]], [])

    assert saved["consumers"][0]["wallbox_assignment"] == {"mode": "fixed", "wallbox_id": "e_auto"}
    created = wallboxes_by_id({"wallboxes": wallboxes})["e_auto"]
    assert (created["voltage_v"], created["phases"], created["max_current_a"]) == (230.0, 1, 16.0)


def test_form_drops_the_view_charger_bindings_of_the_ev():
    from ui.house_config_profile_save import _drop_view_charger_bindings

    item = {
        "type": "ev",
        "ehal_bindings": {
            "evcs.e_auto.set_evcs_max_current": "lox:1",
            "sens_evcs_connected": "lox:2",
            "ev.e_auto.sens_ev_soc": "lox:3",
        },
    }
    _drop_view_charger_bindings(item)
    assert item["ehal_bindings"] == {"ev.e_auto.sens_ev_soc": "lox:3"}

    only_charger = {"type": "ev", "ehal_bindings": {"set_evcs_mode": "lox:4"}}
    _drop_view_charger_bindings(only_charger)
    assert "ehal_bindings" not in only_charger


@pytest.fixture
def wallbox_files(tmp_path, monkeypatch):
    """components.json with wallbox ``wb_a`` (bindings) and ``wb_free``; one EV at ``wb_a``."""
    import config

    components = tmp_path / "components.json"
    house = tmp_path / "house_profiles.json"
    box_a = wallbox_entry(
        "wb_a",
        max_current_a=32.0,
        ehal_bindings={"evcs.wb_a.sens_evcs_connected": "lox:connected"},
    )
    components.write_text(
        json.dumps(
            {
                "earnie_data_model": 6,
                "inverters": [],
                "batteries": [],
                "pv_systems": [],
                "wallboxes": [box_a, wallbox_entry("wb_free")],
            }
        ),
        encoding="utf-8",
    )
    house.write_text(json.dumps(_house(_ev("wb_a", max_current_a=16.0))), encoding="utf-8")
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(components))
    monkeypatch.setenv("EARNIE_HOUSE_PROFILES_PATH", str(house))
    monkeypatch.setattr(config, "reinit_config", lambda *a, **k: None)
    clear_components_doc_cache()
    yield components
    clear_components_doc_cache()


def _stored_wallboxes(path) -> dict[str, dict]:
    return {w["id"]: w for w in json.loads(path.read_text(encoding="utf-8"))["wallboxes"]}


def test_new_wallbox_gets_its_kennung_from_the_label(wallbox_files):
    from ui.house_config_wallbox_io import upsert_wallbox

    fields = {"label": "Wallbox Garage", "voltage_v": 230.0, "phases": 3,
              "min_current_a": 6.0, "max_current_a": 16.0}
    assert upsert_wallbox(fields) == "wallbox_garage"

    stored = _stored_wallboxes(wallbox_files)["wallbox_garage"]
    assert stored["max_current_a"] == 16.0
    # The required setpoint is activated like on every wallbox (dm4 rule).
    assert "evcs.wallbox_garage.set_evcs_max_current" in stored["ehal_bindings"]


def test_update_keeps_kennung_and_bindings(wallbox_files):
    from ui.house_config_wallbox_io import upsert_wallbox

    fields = {"label": "Carport", "voltage_v": 240.0, "phases": 1,
              "min_current_a": 6.0, "max_current_a": 20.0}
    assert upsert_wallbox(fields, stable_id="wb_a") == "wb_a"

    stored = _stored_wallboxes(wallbox_files)["wb_a"]
    assert (stored["label"], stored["voltage_v"], stored["phases"]) == ("Carport", 240.0, 1)
    assert stored["ehal_bindings"]["evcs.wb_a.sens_evcs_connected"] == "lox:connected"


def test_update_without_common_current_for_an_assigned_ev_is_rejected(wallbox_files):
    from ui.house_config_wallbox_io import upsert_wallbox

    before = wallbox_files.read_bytes()
    fields = {"label": "Wallbox wb_a", "voltage_v": 230.0, "phases": 3,
              "min_current_a": 20.0, "max_current_a": 32.0}
    with pytest.raises(ValueError, match="keinen gemeinsamen Ladestrom"):
        upsert_wallbox(fields, stable_id="wb_a")
    assert wallbox_files.read_bytes() == before


def test_delete_of_an_assigned_wallbox_names_the_ev(wallbox_files):
    from ui.house_config_wallbox_io import delete_wallbox

    with pytest.raises(ValueError, match="E-Auto"):
        delete_wallbox("wb_a")
    assert "wb_a" in _stored_wallboxes(wallbox_files)


def test_delete_of_a_free_wallbox(wallbox_files):
    from ui.house_config_wallbox_io import delete_wallbox

    delete_wallbox("wb_free")
    assert set(_stored_wallboxes(wallbox_files)) == {"wb_a"}


def test_two_evs_of_one_profile_at_one_fixed_wallbox_fail_loud():
    """D3: until the dynamic assignment, a wallbox charges one EV per house profile."""
    from house_config.profiles_store import normalize_house_profiles_document

    house = _house(_ev())
    house["profiles"][0]["consumers"].append({**_ev(), "id": "zweitwagen", "label": "Zweitwagen"})
    with pytest.raises(ValueError, match="beide fest der Wallbox 'wb_a'"):
        normalize_house_profiles_document(house, wallboxes=wallbox_catalog(wallbox_entry("wb_a")))


def test_copied_profiles_keep_a_binding_edit_made_on_one_view():
    """The same EV in two profiles shows the wallbox twice; the unchanged view keeps the edit."""
    from house_config.profiles_store import normalize_house_profiles_document

    box = wallbox_entry("wb_a", ehal_bindings={"evcs.wb_a.sens_evcs_connected": "lox:old"})
    house = _house(_ev())
    house["profiles"].append({**house["profiles"][0], "id": "home_copy", "label": "Kopie"})
    view = normalize_house_profiles_document(house, wallboxes=wallbox_catalog(box))
    edited_profile, copy_profile = view["profiles"]["home"], view["profiles"]["home_copy"]
    edited = edited_profile["consumers"][0]
    edited["ehal_bindings"] = {
        **edited["ehal_bindings"], "evcs.e_auto.sens_evcs_connected": "lox:new"
    }

    _, wallboxes = route_evs_to_wallboxes([edited_profile, copy_profile], [box])

    saved = wallboxes_by_id({"wallboxes": wallboxes})["wb_a"]["ehal_bindings"]
    assert saved["evcs.wb_a.sens_evcs_connected"] == "lox:new"
