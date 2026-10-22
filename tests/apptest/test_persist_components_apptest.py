"""Ebene 1 (T1, T2, T5, T8): Komponenten-Formulare (Wechselrichter, PV, Batterie).

Alle drei speichern per ``auto_persist`` (Autosave) in ``components.json``.
Widget-Keys: ``<entity-id>__<suffix>``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from house_config.components_store import (
    clear_components_doc_cache,
    load_components_document,
)
from tests.apptest.fields import COMPONENT_FIELDS, Field

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 15.0


def _new_session(tab: str) -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    at.segmented_control[0].set_value(tab).run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def _widget(at: AppTest, spec: Field):
    return getattr(at, spec.kind)(key=f"{spec.entity}__{spec.suffix}")


def _stored(spec: Field):
    clear_components_doc_cache()
    doc = load_components_document(os.environ["EARNIE_COMPONENTS_PATH"])
    entity = next(e for e in doc[spec.collection] if e["id"] == spec.entity)
    return entity[spec.profile_key]


def _set(at: AppTest, spec: Field, value) -> AppTest:
    _widget(at, spec).set_value(value)
    return at.run(timeout=_TIMEOUT_S)


@pytest.mark.parametrize("spec", COMPONENT_FIELDS, ids=lambda s: f"{s.entity}-{s.suffix}")
def test_t1_value_survives_save_and_new_session(spec: Field) -> None:
    at = _set(_new_session(spec.tab), spec, spec.valid)
    assert not at.exception
    assert _stored(spec) == spec.expected_stored(spec.valid)

    fresh = _new_session(spec.tab)
    assert _widget(fresh, spec).value == spec.valid


def _boundary_params():
    for spec in COMPONENT_FIELDS:
        for value in spec.boundaries:
            yield pytest.param(spec, value, id=f"{spec.entity}-{spec.suffix}-{value}")


@pytest.mark.parametrize("spec,value", list(_boundary_params()))
def test_t2_boundary_values_roundtrip(spec: Field, value) -> None:
    at = _set(_new_session(spec.tab), spec, value)
    assert not at.exception
    assert _stored(spec) == spec.expected_stored(value)
    assert _widget(_new_session(spec.tab), spec).value == value


def test_t5_several_battery_fields_changed_are_all_persisted() -> None:
    by_suffix = {s.suffix: s for s in COMPONENT_FIELDS if s.entity == "test_battery"}
    changes = {
        "planning_battery_capacity": 10.0,
        "planning_battery_min_soc": 20.0,
        "planning_battery_limits_from_live": True,
    }
    at = _new_session("Batterien")
    for suffix, value in changes.items():
        _widget(at, by_suffix[suffix]).set_value(value)
    at.run(timeout=_TIMEOUT_S)
    assert not at.exception
    for suffix, value in changes.items():
        assert _stored(by_suffix[suffix]) == value, suffix


def test_t8_second_session_sees_value_saved_by_first() -> None:
    spec = next(s for s in COMPONENT_FIELDS if s.suffix == "planning_pv_kwp")
    _set(_new_session(spec.tab), spec, 7.7)
    assert _widget(_new_session(spec.tab), spec).value == 7.7


# --- T3: abgelehnte Eingaben -----------------------------------------------------------

_COMPONENTS_PATH_ENV = "EARNIE_COMPONENTS_PATH"
_SECOND_ENTITIES = (("inverters", "wr_zweit"), ("pv_systems", "pv_zweit"), ("batteries", "bat_zweit"))


@pytest.fixture
def second_entities():
    """Je ein zweiter Wechselrichter, PV-Feld und Batterie, damit Bezeichnungen kollidieren können."""
    import copy
    import json

    path = os.environ[_COMPONENTS_PATH_ENV]
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    for collection, entity_id in _SECOND_ENTITIES:
        clone = copy.deepcopy(doc[collection][0])
        clone["id"] = entity_id
        clone["label"] = f"Zweite {entity_id}"
        doc[collection].append(clone)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False)
    clear_components_doc_cache()


def _field(suffix: str) -> Field:
    return next(s for s in COMPONENT_FIELDS if s.suffix == suffix)


# Bekannte Fehler: Test bleibt stehen, schlägt streng fehl, sobald der Fehler behoben ist.
_DUPLICATE_LABEL_BUG = (
    "Autosave: upsert_* lehnt ab, _save_* zeigt st.error und liefert None, auto_persist wertet das "
    "als Erfolg ('Gespeichert') und st.rerun() verwirft die Meldung (Backlog-Bugfixes)"
)
_EMPTY_LABEL_SILENT_BUG = (
    "Bei leerer Bezeichnung wird nicht gespeichert, aber (anders als bei der Batterie) "
    "weist keine Meldung darauf hin (Backlog-Bugfixes)"
)


@pytest.mark.parametrize(
    "suffix,duplicate",
    [
        pytest.param("planning_inv_label", "Zweite wr_zweit", marks=pytest.mark.xfail(reason=_DUPLICATE_LABEL_BUG, strict=True)),
        pytest.param("planning_pv_label", "zweite pv_zweit", marks=pytest.mark.xfail(reason=_DUPLICATE_LABEL_BUG, strict=True)),
        pytest.param("planning_battery_label", "ZWEITE bat_zweit", marks=pytest.mark.xfail(reason=_DUPLICATE_LABEL_BUG, strict=True)),
    ],
)
def test_t3_duplicate_label_shows_error_and_keeps_file(second_entities, suffix: str, duplicate: str) -> None:
    spec = _field(suffix)
    path = Path(os.environ[_COMPONENTS_PATH_ENV])
    at = _new_session(spec.tab)
    before = path.read_bytes()

    at = _set(at, spec, duplicate)

    assert not at.exception
    assert path.read_bytes() == before
    assert at.error, "doppelte Bezeichnung muss als Fehlermeldung sichtbar sein"
    assert not any("Gespeichert" in c.value for c in at.caption)


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param("planning_inv_label", marks=pytest.mark.xfail(reason=_EMPTY_LABEL_SILENT_BUG, strict=True)),
        pytest.param("planning_pv_label", marks=pytest.mark.xfail(reason=_EMPTY_LABEL_SILENT_BUG, strict=True)),
        "planning_battery_label",
    ],
)
def test_t3_empty_label_is_not_saved_and_user_is_told(suffix: str) -> None:
    spec = _field(suffix)
    path = Path(os.environ[_COMPONENTS_PATH_ENV])
    at = _new_session(spec.tab)
    before = path.read_bytes()

    at = _set(at, spec, "")

    assert not at.exception
    assert path.read_bytes() == before
    assert at.error or at.warning, "leere Bezeichnung muss einen sichtbaren Hinweis auslösen"
    assert _widget(_new_session(spec.tab), spec).value != ""


@pytest.mark.xfail(
    reason="Batterie-Formular akzeptiert max. SoC unter min. SoC ohne Meldung (Backlog-Bugfixes)",
    strict=True,
)
def test_t3_battery_max_soc_below_min_soc_is_rejected() -> None:
    min_spec, max_spec = _field("planning_battery_min_soc"), _field("planning_battery_max_soc")
    path = Path(os.environ[_COMPONENTS_PATH_ENV])
    at = _new_session(max_spec.tab)
    before = path.read_bytes()
    min_soc = _widget(at, min_spec).value

    at = _set(at, max_spec, min_soc - 5.0)

    assert not at.exception
    assert at.error or at.warning
    assert path.read_bytes() == before
