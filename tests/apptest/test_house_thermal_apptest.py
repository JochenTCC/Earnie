"""Hauskonfigurator: section „Gebäude / Wärmebedarf“ with the switch „Heizung betrachten“.

The fixture house ``test_home`` has „Heizung betrachten“ on, the thermal_annual consumer
``wp`` and its building data at house level (``thermal``). Covered: the house fields survive
save + new session (T1, T2), the switch hides the section and the consumer without losing
stored values, and a house without heating can turn it on.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from house_config.profiles_store import (
    clear_house_profiles_doc_cache,
    load_house_profiles_document,
)
from tests.apptest.fields import HOUSE_THERMAL_FIELDS, Field
from tests.apptest.helpers import assert_clean

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_PROFILE_ID = "test_home"
_KEY_PREFIX = f"{_PROFILE_ID}__"
_SWITCH = f"{_KEY_PREFIX}house_heating_enabled"
_AREA = f"{_KEY_PREFIX}house_thermal_area"
# Generation field of the „Haus Wärme“ consumer (index 0).
_WP_NOM = f"{_KEY_PREFIX}hc_g0_nom_0"


@pytest.fixture(autouse=True)
def _room_for_baseload(_isolated_backtesting_config):
    from house_config.components_store import clear_components_doc_cache
    from tests.conftest import _reinit_config_offline

    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    house = json.loads(path.read_text(encoding="utf-8"))
    # Room for the baseload check, as in test_persist_consumers_apptest.
    house["profiles"][0]["annual_kwh"] = 200000.0
    path.write_text(json.dumps(house, ensure_ascii=False), encoding="utf-8")
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()
    _reinit_config_offline()
    yield


def _new_session() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert_clean(at)
    assert not at.error, [e.value for e in at.error]
    return at


def _raw_profile() -> dict:
    doc = json.loads(Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"]).read_text(encoding="utf-8"))
    return next(p for p in doc["profiles"] if p["id"] == _PROFILE_ID)


def _loaded_profile() -> dict:
    clear_house_profiles_doc_cache()
    doc = load_house_profiles_document(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    return doc["profiles"][_PROFILE_ID]


def _dig(obj, dotted: str):
    for part in dotted.split("."):
        obj = obj[part]
    return obj


def _widget(at: AppTest, spec: Field):
    return getattr(at, spec.kind)(key=_KEY_PREFIX + spec.suffix)


def _keys(at: AppTest) -> set[str]:
    return {w.key for kind in ("number_input", "checkbox", "selectbox") for w in getattr(at, kind)}


def _set_switch(at: AppTest, value: bool) -> AppTest:
    at.checkbox(key=_SWITCH).set_value(value)
    at.run(timeout=_TIMEOUT_S)
    assert_clean(at)
    assert not at.error, [e.value for e in at.error]
    return at


@pytest.mark.parametrize("spec", HOUSE_THERMAL_FIELDS, ids=lambda s: s.id)
def test_t1_house_field_survives_save_and_new_session(spec: Field) -> None:
    at = _new_session()
    _widget(at, spec).set_value(spec.valid)
    at.run(timeout=_TIMEOUT_S)
    assert_clean(at)
    assert _dig(_raw_profile(), spec.profile_key) == spec.valid
    assert _widget(_new_session(), spec).value == spec.valid


def _boundary_params():
    for spec in HOUSE_THERMAL_FIELDS:
        for value in spec.boundaries:
            yield pytest.param(spec, value, id=f"{spec.id}-{value}")


@pytest.mark.parametrize("spec,value", list(_boundary_params()))
def test_t2_house_field_boundaries_roundtrip(spec: Field, value) -> None:
    at = _new_session()
    _widget(at, spec).set_value(value)
    at.run(timeout=_TIMEOUT_S)
    assert_clean(at)
    assert _dig(_raw_profile(), spec.profile_key) == value
    assert _widget(_new_session(), spec).value == value


def test_house_values_reach_the_planned_heating_consumer() -> None:
    at = _new_session()
    at.number_input(key=_AREA).set_value(175.0)
    at.number_input(key=f"{_KEY_PREFIX}house_persons").set_value(3)
    at.run(timeout=_TIMEOUT_S)
    assert_clean(at)
    wp = next(c for c in _loaded_profile()["consumers"] if c["id"] == "wp")
    assert wp["thermal"]["living_area_m2"] == 175.0
    assert wp["thermal"]["persons"] == 3
    raw_wp = next(c for c in _raw_profile()["consumers"] if c["id"] == "wp")
    assert "living_area_m2" not in raw_wp and "persons" not in raw_wp


def test_switch_off_hides_section_and_consumer_and_keeps_values() -> None:
    at = _new_session()
    at.number_input(key=_AREA).set_value(166.0)
    at.run(timeout=_TIMEOUT_S)
    assert_clean(at)
    assert _WP_NOM in _keys(at)

    at = _set_switch(at, False)
    keys = _keys(at)
    assert _AREA not in keys
    assert _WP_NOM not in keys
    raw = _raw_profile()
    assert raw["heating_enabled"] is False
    assert raw["thermal"]["living_area_m2"] == 166.0
    assert any(c["id"] == "wp" for c in raw["consumers"])
    loaded = _loaded_profile()
    # Not planned: the heating stays in the baseload.
    assert all(c["type"] != "thermal_annual" for c in loaded["consumers"])

    fresh = _new_session()
    assert fresh.checkbox(key=_SWITCH).value is False
    assert _AREA not in _keys(fresh)

    fresh = _set_switch(fresh, True)
    assert fresh.number_input(key=_AREA).value == 166.0
    assert _WP_NOM in _keys(fresh)
    raw = _raw_profile()
    assert raw["heating_enabled"] is True
    assert raw["thermal"]["living_area_m2"] == 166.0
    wp = next(c for c in _loaded_profile()["consumers"] if c["id"] == "wp")
    assert wp["heating_system_id"] == "heating_test_home"


def test_switch_off_hides_haus_waerme_from_the_type_options() -> None:
    at = _new_session()
    at = _set_switch(at, False)
    # Consumer 1 (``wasch`` etc. are not in this fixture): add one and check its type list.
    at.button(key=f"{_KEY_PREFIX}house_consumer_add").click().run(timeout=_TIMEOUT_S)
    assert_clean(at)
    type_box = next(s for s in at.selectbox if s.key.endswith("_type_1"))
    assert "thermal_annual" not in type_box.options and "Haus Wärme" not in type_box.options


def test_house_without_heating_turns_it_on() -> None:
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    house = json.loads(path.read_text(encoding="utf-8"))
    profile = house["profiles"][0]
    profile["consumers"] = [c for c in profile["consumers"] if c["type"] != "thermal_annual"]
    profile["heating_enabled"] = False
    profile.pop("thermal", None)
    path.write_text(json.dumps(house, ensure_ascii=False), encoding="utf-8")
    clear_house_profiles_doc_cache()

    at = _new_session()
    assert at.checkbox(key=_SWITCH).value is False
    assert _AREA not in _keys(at)

    at = _set_switch(at, True)
    assert at.number_input(key=_AREA).value == 120.0
    raw = _raw_profile()
    assert raw["heating_enabled"] is True
    assert raw["thermal"]["living_area_m2"] == 120.0
