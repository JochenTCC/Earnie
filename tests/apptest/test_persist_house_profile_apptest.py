"""Ebene 1 (T1, T2, T5, T8): Hausprofil-Felder überleben Speichern + neue Session.

Der Hauskonfigurator speichert automatisch bei Änderung (``auto_persist``);
"Speichern" ist hier also der Rerun nach ``set_value``. Eine neue
``AppTest``-Instanz entspricht einer frischen Browser-Session.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from house_config.profiles_store import (
    clear_house_profiles_doc_cache,
    load_house_profiles_document,
)
from tests.apptest.fields import HOUSE_PROFILE_FIELDS, Field

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 15.0
_PROFILE_ID = "test_home"
_KEY_PREFIX = f"{_PROFILE_ID}__"


def _new_session() -> AppTest:
    return AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)


def _widget(at: AppTest, spec: Field):
    return getattr(at, spec.kind)(key=_KEY_PREFIX + spec.suffix)


def _stored_profile() -> dict:
    clear_house_profiles_doc_cache()
    doc = load_house_profiles_document(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    return doc["profiles"][_PROFILE_ID]


def _set(at: AppTest, spec: Field, value) -> AppTest:
    _widget(at, spec).set_value(value)
    return at.run(timeout=_TIMEOUT_S)


@pytest.mark.parametrize("spec", HOUSE_PROFILE_FIELDS, ids=lambda s: s.id)
def test_t1_value_survives_save_and_new_session(spec: Field) -> None:
    at = _new_session()
    assert not at.exception
    at = _set(at, spec, spec.valid)
    assert not at.exception

    assert _stored_profile()[spec.profile_key] == spec.valid

    fresh = _new_session()
    assert not fresh.exception
    value = _widget(fresh, spec).value
    assert value == spec.valid
    assert type(value) is type(spec.valid) or spec.kind == "number_input"


def _boundary_params():
    for spec in HOUSE_PROFILE_FIELDS:
        for value in spec.boundaries:
            yield pytest.param(spec, value, id=f"{spec.id}-{value}")


@pytest.mark.parametrize("spec,value", list(_boundary_params()))
def test_t2_boundary_values_roundtrip(spec: Field, value) -> None:
    at = _set(_new_session(), spec, value)
    assert not at.exception
    assert _stored_profile()[spec.profile_key] == value
    assert _widget(_new_session(), spec).value == value


def _rejected_params():
    for spec in HOUSE_PROFILE_FIELDS:
        for value in spec.rejected:
            yield pytest.param(spec, value, id=f"{spec.id}-{value}")


@pytest.mark.parametrize("spec,value", list(_rejected_params()))
def test_t3_rejected_value_shows_error_and_keeps_storage(spec: Field, value) -> None:
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    at = _new_session()
    # Der erste Render normalisiert die Fixture-Datei per Autosave; erst danach vergleichen.
    before = path.read_bytes()

    at = _set(at, spec, value)

    assert not at.exception
    assert at.error, "Ablehnung muss als Fehlermeldung sichtbar sein"
    assert path.read_bytes() == before
    assert _widget(_new_session(), spec).value != value


def test_t5_several_fields_changed_are_all_persisted() -> None:
    at = _new_session()
    by_suffix = {s.suffix: s for s in HOUSE_PROFILE_FIELDS}
    changes = {
        "house_annual_kwh": 6100.0,
        "house_absent_mode": True,
        "house_profile_default_pv_tilt": 40,
    }
    for suffix, value in changes.items():
        _widget(at, by_suffix[suffix]).set_value(value)
    at.run(timeout=_TIMEOUT_S)
    assert not at.exception

    stored = _stored_profile()
    for suffix, value in changes.items():
        assert stored[by_suffix[suffix].profile_key] == value, suffix


def test_t8_second_session_sees_value_saved_by_first() -> None:
    spec = next(s for s in HOUSE_PROFILE_FIELDS if s.suffix == "house_annual_kwh")
    session_b = _new_session()  # B öffnet vor dem Speichern
    assert _widget(session_b, spec).value == 4000.0

    _set(_new_session(), spec, 7777.0)  # Session A speichert

    assert _widget(_new_session(), spec).value == 7777.0  # frische Session sieht neu
