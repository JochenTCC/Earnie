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
