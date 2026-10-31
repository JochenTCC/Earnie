"""Hausprofil: Region setzt den Netzbereich, wenn genau einer in ihr liegt (Dogfooding-Fund).

Österreich hat 9 Bundesländer und 14 Netzbereiche; eindeutig sind Burgenland (1),
Niederösterreich (3), Salzburg (5) und Wien (9). In den übrigen Ländern liegt zusätzlich
ein Stadt- bzw. Talnetz (Klagenfurt, Linz, Graz, Innsbruck, Kleinwalsertal) — dort
wählt der Benutzer. Ein gewählter Netzbereich, der in der Region liegt, und
*Eigener Arbeitspreis* bleiben stehen.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from house_config.own_grid_fee import OWN_AREA
from tests.apptest.helpers import assert_clean, messages

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_FIXTURE_PROFILE = "test_home"
_NEW_OPTION = "— neu —"


def _stored_profiles() -> dict:
    with open(os.environ["EARNIE_HOUSE_PROFILES_PATH"], encoding="utf-8") as handle:
        return {p["id"]: p for p in json.load(handle)["profiles"]}


def _new_profile_session() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    at.selectbox(key="house_profile_select").set_value(_NEW_OPTION).run(timeout=_TIMEOUT_S)
    assert_clean(at)
    return at


def _created_profile() -> tuple[str, dict]:
    [(profile_id, profile)] = [
        (pid, p) for pid, p in _stored_profiles().items() if pid != _FIXTURE_PROFILE
    ]
    return profile_id, profile


def test_unique_region_sets_grid_area_and_saves_it() -> None:
    at = _new_profile_session()

    at.selectbox(key="__new____house_profile_region_AT").set_value("5").run(timeout=_TIMEOUT_S)

    assert_clean(at)
    profile_id, profile = _created_profile()
    assert (profile["region"], profile["netznutzung"]["area_id"]) == ("5", "AT-SBG")
    assert at.selectbox(key=f"{profile_id}__house_profile_nne_area").value == "AT-SBG"
    captions = messages(at)["caption"]
    assert any("Einziger Netzbereich" in text and "Salzburg" in text for text in captions)


def test_region_with_several_grid_areas_leaves_the_choice_to_the_user() -> None:
    at = _new_profile_session()

    at.selectbox(key="__new____house_profile_region_AT").set_value("4").run(timeout=_TIMEOUT_S)

    assert_clean(at)
    assert at.selectbox(key="__new____house_profile_nne_area").value is None
    assert any("Netzbereich wählen" in text for text in messages(at)["warning"])
    assert set(_stored_profiles()) == {_FIXTURE_PROFILE}


def test_chosen_grid_area_in_the_region_is_kept() -> None:
    at = _new_profile_session()
    at.selectbox(key="__new____house_profile_nne_area").set_value("AT-LINZ").run(timeout=_TIMEOUT_S)
    profile_id, _profile = _created_profile()

    at.selectbox(key=f"{profile_id}__house_profile_region_AT").set_value("4").run(timeout=_TIMEOUT_S)

    assert_clean(at)
    assert at.selectbox(key=f"{profile_id}__house_profile_nne_area").value == "AT-LINZ"
    assert _stored_profiles()[profile_id]["netznutzung"]["area_id"] == "AT-LINZ"
    assert not any("Einziger Netzbereich" in text for text in messages(at)["caption"])


def test_grid_area_of_another_region_is_replaced_with_notice() -> None:
    at = _new_profile_session()
    at.selectbox(key="__new____house_profile_nne_area").set_value("AT-VBG").run(timeout=_TIMEOUT_S)
    profile_id, _profile = _created_profile()

    at.selectbox(key=f"{profile_id}__house_profile_region_AT").set_value("9").run(timeout=_TIMEOUT_S)

    assert_clean(at)
    assert at.selectbox(key=f"{profile_id}__house_profile_nne_area").value == "AT-WIEN"
    assert _stored_profiles()[profile_id]["netznutzung"]["area_id"] == "AT-WIEN"
    captions = messages(at)["caption"]
    assert any("Einziger Netzbereich" in text and "Wien" in text for text in captions)


def test_own_grid_fee_is_kept_when_region_changes() -> None:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    area_key = f"{_FIXTURE_PROFILE}__house_profile_nne_area"
    assert at.selectbox(key=area_key).value == OWN_AREA

    at.selectbox(key=f"{_FIXTURE_PROFILE}__house_profile_region_AT").set_value("9").run(
        timeout=_TIMEOUT_S
    )

    assert_clean(at)
    assert at.selectbox(key=area_key).value == OWN_AREA
    assert _stored_profiles()[_FIXTURE_PROFILE]["netznutzung"]["area_id"] == "user_test_home"
