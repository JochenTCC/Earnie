"""Ebene 1 (T6-Vorstufe, L8): Profil- und Szenariowechsel zeigen keine Werte des alten Objekts.

Die Formulare halten ihre Widget-Werte unter ``<id>__<feld>`` (``session_scope``).
Nach dem Wechsel muss jedes Feld den Wert des neu gewählten Objekts aus der Datei
zeigen, nicht den des vorigen. Der Wechsel passiert im selben ``AppTest`` (also in
derselben Session), eine neue Instanz würde den Session-State verwerfen.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_SCRIPTS = Path(__file__).parent / "scripts"
_TIMEOUT_S = 30.0

# --- Hausprofil -------------------------------------------------------------------------

_PROFILE_A = "test_home"
_PROFILE_B = "zweit_haus"
_LABEL_A = "Test-Haushalt 4000 kWh/a"
_LABEL_B = "Zweites Haus"
_NEW_OPTION = "— neu —"

# (Widget-Suffix im Scope, Widget-Art, Wert in B)
_PROFILE_B_VALUES = {
    "house_profile_label": ("text_input", _LABEL_B),
    "house_annual_kwh": ("number_input", 60000.0),
    "house_absent_mode": ("checkbox", True),
    "house_profile_land": ("selectbox", "DE"),
    "house_profile_latitude": ("number_input", 52.52),
    "house_profile_longitude": ("number_input", 13.4),
    "house_profile_default_pv_tilt": ("number_input", 40),
    "house_profile_default_pv_azimuth": ("number_input", -30),
}


@pytest.fixture
def two_profiles():
    path = os.environ["EARNIE_HOUSE_PROFILES_PATH"]
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    clone = copy.deepcopy(doc["profiles"][0])
    clone.update(
        id=_PROFILE_B, label=_LABEL_B, annual_kwh=60000.0, absent_mode=True, land="DE",
        latitude=52.52, longitude=13.4, default_pv_tilt=40, default_pv_azimuth=-30,
    )
    doc["profiles"].append(clone)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False)
    from house_config.profiles_store import clear_house_profiles_doc_cache

    clear_house_profiles_doc_cache()


def _house_session() -> AppTest:
    at = AppTest.from_file(str(_SCRIPTS / "run_page_house_config.py")).run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def _select_profile(at: AppTest, display: str) -> AppTest:
    at.selectbox(key="house_profile_select").set_value(display).run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def _profile_values(at: AppTest, scope: str) -> dict:
    return {
        suffix: getattr(at, kind)(key=f"{scope}__{suffix}").value
        for suffix, (kind, _value) in _PROFILE_B_VALUES.items()
    }


def test_l8_profile_switch_shows_values_of_new_profile(two_profiles) -> None:
    at = _house_session()
    values_a = _profile_values(at, _PROFILE_A)  # A ist die Vorauswahl

    _select_profile(at, _LABEL_B)

    values_b = _profile_values(at, _PROFILE_B)
    assert values_b == {suffix: value for suffix, (_kind, value) in _PROFILE_B_VALUES.items()}
    assert all(values_b[s] != values_a[s] for s in values_a if s != "house_profile_land")


def test_l8_profile_switch_back_restores_first_profile(two_profiles) -> None:
    at = _house_session()
    values_a = _profile_values(at, _PROFILE_A)
    _select_profile(at, _LABEL_B)

    _select_profile(at, _LABEL_A)

    assert _profile_values(at, _PROFILE_A) == values_a


def test_l8_edit_in_profile_a_does_not_leak_into_b(two_profiles) -> None:
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    at = _house_session()
    at.number_input(key=f"{_PROFILE_A}__house_annual_kwh").set_value(4321.0).run(timeout=_TIMEOUT_S)
    assert not at.exception

    _select_profile(at, _LABEL_B)

    assert at.number_input(key=f"{_PROFILE_B}__house_annual_kwh").value == 60000.0
    assert at.text_input(key=f"{_PROFILE_B}__house_profile_label").value == _LABEL_B
    with open(path, encoding="utf-8") as handle:
        stored = {p["id"]: p for p in json.load(handle)["profiles"]}
    assert stored[_PROFILE_A]["annual_kwh"] == 4321.0
    assert stored[_PROFILE_B]["annual_kwh"] == 60000.0
    assert stored[_PROFILE_B]["label"] == _LABEL_B


def _new_profile_from_b() -> tuple[AppTest, dict]:
    """Wählt "— neu —" aus Profil B; das Formular legt das Profil mit Standardwerten sofort an."""
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    at = _house_session()
    _select_profile(at, _LABEL_B)
    _select_profile(at, _NEW_OPTION)
    with open(path, encoding="utf-8") as handle:
        stored = {p["id"]: p for p in json.load(handle)["profiles"]}
    created = [p for pid, p in stored.items() if pid not in (_PROFILE_A, _PROFILE_B)]
    assert len(created) == 1, "genau ein neues Profil erwartet"
    return at, created[0]


def test_l8_new_profile_starts_from_defaults_not_from_previous_profile(two_profiles) -> None:
    _at, created = _new_profile_from_b()

    assert created["label"] == "Mein Haushalt"
    assert created["annual_kwh"] == 4500.0
    assert created["absent_mode"] is False
    assert created["land"] != "DE" or created["latitude"] != 52.52
    assert (created["latitude"], created["longitude"]) != (52.52, 13.4)
    assert created["default_pv_tilt"] != 40
    assert created["consumers"] == []


@pytest.mark.xfail(
    strict=True,
    reason="house_config_profile_save._perform_house_profile_save legt das neue Profil sofort an und "
    "setzt die Auswahl auf die id; _align_profile_select_session erwartet das Anzeige-Label und "
    "springt auf das vorige Profil zurück (Backlog-Bugfixes)",
)
def test_l8_new_profile_selection_does_not_jump_back_to_previous_profile(two_profiles) -> None:
    at, _created = _new_profile_from_b()

    assert at.selectbox(key="house_profile_select").value in (_NEW_OPTION, "Mein Haushalt")


# --- Szenarienkonfigurator --------------------------------------------------------------

_SCENARIO_A = "entity_test"
_SCENARIO_B = "fixture_5kwh_fixed"
_RADIO_A = "Entitäten-Referenzen Test"
_RADIO_B = "Fixture 5 kWh fixe Einspeise"


def _scenario_session() -> AppTest:
    at = AppTest.from_file(str(_SCRIPTS / "run_page_scenario_editor.py")).run(timeout=_TIMEOUT_S)
    at.radio(key="scenario_select").set_value(_RADIO_A).run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def _select_scenario(at: AppTest, radio_label: str) -> AppTest:
    at.radio(key="scenario_select").set_value(radio_label).run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def test_l8_scenario_switch_shows_values_of_new_scenario() -> None:
    at = _scenario_session()
    assert at.text_input(key=f"{_SCENARIO_A}__scenario_label").value == _RADIO_A
    assert at.multiselect(key=f"{_SCENARIO_A}__scenario_battery").value != []

    _select_scenario(at, _RADIO_B)

    assert at.text_input(key=f"{_SCENARIO_B}__scenario_label").value == _RADIO_B
    assert at.multiselect(key=f"{_SCENARIO_B}__scenario_battery").value == []
    assert at.multiselect(key=f"{_SCENARIO_B}__scenario_pv").value == []
    assert at.selectbox(key=f"{_SCENARIO_B}__scenario_profile").value == "— keine —"
    assert not any(
        str(w.key).startswith(f"{_SCENARIO_A}__") for w in at.text_input if w.key
    ), "Widgets des alten Szenarios dürfen nach dem Wechsel nicht mehr gerendert werden"


def test_l8_scenario_switch_back_restores_first_scenario() -> None:
    at = _scenario_session()
    before = {
        "label": at.text_input(key=f"{_SCENARIO_A}__scenario_label").value,
        "battery": at.multiselect(key=f"{_SCENARIO_A}__scenario_battery").value,
        "pv": at.multiselect(key=f"{_SCENARIO_A}__scenario_pv").value,
        "profile": at.selectbox(key=f"{_SCENARIO_A}__scenario_profile").value,
    }
    _select_scenario(at, _RADIO_B)

    _select_scenario(at, _RADIO_A)

    assert {
        "label": at.text_input(key=f"{_SCENARIO_A}__scenario_label").value,
        "battery": at.multiselect(key=f"{_SCENARIO_A}__scenario_battery").value,
        "pv": at.multiselect(key=f"{_SCENARIO_A}__scenario_pv").value,
        "profile": at.selectbox(key=f"{_SCENARIO_A}__scenario_profile").value,
    } == before


def test_l8_edit_in_scenario_a_does_not_leak_into_b() -> None:
    path = Path(os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"])
    at = _scenario_session()
    at.text_input(key=f"{_SCENARIO_A}__scenario_label").set_value("Geändert A").run(timeout=_TIMEOUT_S)
    assert not at.exception

    _select_scenario(at, _RADIO_B)

    assert at.text_input(key=f"{_SCENARIO_B}__scenario_label").value == _RADIO_B
    with open(path, encoding="utf-8") as handle:
        stored = {s["id"]: s for s in json.load(handle)["scenarios"]}
    assert stored[_SCENARIO_A]["label"] == "Geändert A"
    assert stored[_SCENARIO_B]["label"] == _RADIO_B
