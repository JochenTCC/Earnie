"""Ebene 1 (T1, T3, T5, T8): Szenarienkonfigurator.

Autosave (``auto_persist``) in ``backtesting_scenarios.json``. Getestet wird das
Nicht-Live-Szenario ``entity_test``: Widget-Keys ``entity_test__<suffix>``, die
Auswahl erfolgt über das Radio ``scenario_select``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.apptest.fields import (
    ABSENT,
    SCENARIO_FIELDS,
    SCENARIO_ID,
    SCENARIO_RADIO_LABEL,
    Field,
)

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"
_TIMEOUT_S = 30.0


def _new_session(radio_label: str = SCENARIO_RADIO_LABEL) -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    at.radio(key="scenario_select").set_value(radio_label).run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def _widget(at: AppTest, spec: Field):
    return getattr(at, spec.kind)(key=f"{spec.entity}__{spec.suffix}")


def _scenarios_path() -> str:
    return os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"]


def _stored(spec: Field):
    with open(_scenarios_path(), encoding="utf-8") as handle:
        doc = json.load(handle)
    obj = next(s for s in doc["scenarios"] if s["id"] == spec.entity)
    for part in spec.profile_key.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return ABSENT
        obj = obj[part]
    return obj


def _expected(spec: Field):
    return spec.stored if spec.stored is not None else spec.valid


def _set(at: AppTest, spec: Field, value) -> AppTest:
    _widget(at, spec).set_value(value)
    return at.run(timeout=_TIMEOUT_S)


def _ids(spec: Field) -> str:
    return f"{spec.suffix}-{str(spec.valid)[:12]}"


@pytest.mark.parametrize("spec", SCENARIO_FIELDS, ids=_ids)
def test_t1_value_survives_save_and_new_session(spec: Field) -> None:
    at = _set(_new_session(), spec, spec.valid)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert _stored(spec) == _expected(spec)

    # Nach dem Umbenennen heißt der Radio-Eintrag wie die neue Bezeichnung.
    reopened = spec.valid if spec.suffix == "scenario_label" else SCENARIO_RADIO_LABEL
    assert _widget(_new_session(reopened), spec).value == spec.valid


def test_t3_duplicate_label_is_rejected_and_file_stays_unchanged() -> None:
    label_spec = next(s for s in SCENARIO_FIELDS if s.suffix == "scenario_label")
    at = _new_session()
    before = Path(_scenarios_path()).read_bytes()  # nach dem ersten Render (Autosave)

    at = _set(at, label_spec, "Fixture 5 kWh fixe Einspeise")  # Bezeichnung existiert schon

    assert not at.exception
    assert Path(_scenarios_path()).read_bytes() == before
    assert at.error, "Ablehnung muss als Fehlermeldung sichtbar bleiben"


def test_t3_duplicate_label_does_not_change_the_file() -> None:
    """Teil von T3, der heute schon gilt: Speicher bleibt unverändert."""
    label_spec = next(s for s in SCENARIO_FIELDS if s.suffix == "scenario_label")
    at = _new_session()
    before = Path(_scenarios_path()).read_bytes()
    _set(at, label_spec, "Fixture 5 kWh fixe Einspeise")
    assert Path(_scenarios_path()).read_bytes() == before


@pytest.mark.parametrize(
    "land,side,label,stored_key,stored_id",
    [
        ("DE", "import", "DE Spot Test", "settings.import_tariff_id", "de_spot_test"),
        ("CH", "export", "CH Fix Test", "settings.export_tariff_id", "ch_fix_test"),
    ],
)
def test_l7_land_filter_then_tariff_is_persisted(land, side, label, stored_key, stored_id) -> None:
    """Abhängige Felder: Land-Filter (nicht gespeichert) -> Tarif-Auswahl (gespeichert)."""
    prefix = f"{SCENARIO_ID}__"
    at = _new_session()
    at.selectbox(key=prefix + "scenario_tariff_land").set_value(land).run(timeout=_TIMEOUT_S)
    assert not at.exception
    at.selectbox(key=prefix + f"scenario_{side}").set_value(label).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]

    spec = Field("selectbox", f"scenario_{side}", stored_key, label, entity=SCENARIO_ID)
    assert _stored(spec) == stored_id
    # Der Land-Filter wird nicht gespeichert; der gespeicherte Tarif bleibt trotzdem wählbar.
    assert _widget(_new_session(), spec).value == label


def test_t5_several_fields_changed_are_all_persisted() -> None:
    by_key = {}
    for spec in SCENARIO_FIELDS:
        by_key.setdefault(spec.suffix, spec)
    picks = ["scenario_enabled", "scenario_own_reference", "scenario_battery"]
    at = _new_session()
    for suffix in picks:
        _widget(at, by_key[suffix]).set_value(by_key[suffix].valid)
    at.run(timeout=_TIMEOUT_S)
    assert not at.exception
    for suffix in picks:
        assert _stored(by_key[suffix]) == _expected(by_key[suffix]), suffix


def test_t8_second_session_sees_value_saved_by_first() -> None:
    spec = next(s for s in SCENARIO_FIELDS if s.suffix == "scenario_enabled")
    _set(_new_session(), spec, False)
    assert _widget(_new_session(), spec).value is False


def test_live_scenario_label_is_locked() -> None:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert at.text_input(key="live__scenario_label").disabled
