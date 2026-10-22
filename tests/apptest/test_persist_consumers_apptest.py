"""Ebene 1 (T1, T2, T5): Verbraucher-Gruppen im Hausprofil.

Das Fixture-Profil enthält nur "Haus Wärme" (``wp``). Das Fixture hier ergänzt je
einen allgemeinen (``wasch``), einen E-Auto- (``ev1``) und einen RC-Verbraucher
(``pool``) und hebt den Jahresverbrauch an, damit die Grundlast-Prüfung nicht
das Speichern blockiert. Autosave wie beim Hausprofil.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from house_config.profiles_store import clear_house_profiles_doc_cache
from tests.apptest.fields import CONSUMER_FIELDS, Field

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_PROFILE_ID = "test_home"
_KEY_PREFIX = f"{_PROFILE_ID}__hc_g0_"

_EXTRA_CONSUMERS = [
    {
        "id": "wasch", "label": "Waschmaschine", "type": "generic",
        "annual_kwh": 300.0, "nominal_power_kw": 2.0,
        "schedule": {"runs_per_week": 3, "duration_h": 2.0, "start_hour": 10, "start_shift_h": 1.0},
    },
    {
        "id": "ev1", "label": "Auto", "type": "ev",
        "battery_capacity_kwh": 50.0, "nominal_power_kw": 11.0,
        "charging_schedule": {
            "weekday": {"car_available_from_hour": 15, "ready_by_hour": 7, "daily_rest_soc": 20.0},
        },
    },
    {
        "id": "pool", "label": "Pool", "type": "thermal_rc", "nominal_power_kw": 2.0,
        "water_volume_liters": 1000.0, "heating_efficiency": 0.9,
        "heat_loss_kw_per_k": 0.05, "setpoint_c": 25.0, "tolerance_c": 1.0,
    },
]


@pytest.fixture(autouse=True)
def _profile_with_all_consumer_types():
    path = os.environ["EARNIE_HOUSE_PROFILES_PATH"]
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    doc["profiles"][0]["annual_kwh"] = 200000.0
    doc["profiles"][0]["consumers"] += _EXTRA_CONSUMERS
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False)
    clear_house_profiles_doc_cache()


def _new_session() -> AppTest:
    return AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)


def _widget(at: AppTest, spec: Field):
    return getattr(at, spec.kind)(key=_KEY_PREFIX + spec.suffix)


def _dig(obj, dotted: str):
    for part in dotted.split("."):
        obj = obj[part]
    return obj


def _stored(spec: Field):
    # Rohdatei statt normalisiertem Loader: der Loader legt thermal_annual-Felder anders ab.
    with open(os.environ["EARNIE_HOUSE_PROFILES_PATH"], encoding="utf-8") as handle:
        doc = json.load(handle)
    profile = next(p for p in doc["profiles"] if p["id"] == _PROFILE_ID)
    consumer = next(c for c in profile["consumers"] if c["id"] == spec.entity)
    return _dig(consumer, spec.profile_key)


def _set(at: AppTest, spec: Field, value) -> AppTest:
    _widget(at, spec).set_value(value)
    return at.run(timeout=_TIMEOUT_S)


def _ids(spec: Field) -> str:
    return f"{spec.entity}-{spec.suffix}"


@pytest.mark.parametrize("spec", CONSUMER_FIELDS, ids=_ids)
def test_t1_value_survives_save_and_new_session(spec: Field) -> None:
    at = _new_session()
    assert not at.exception
    at = _set(at, spec, spec.valid)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert _stored(spec) == spec.valid

    assert _widget(_new_session(), spec).value == spec.valid


def _boundary_params():
    for spec in CONSUMER_FIELDS:
        for value in spec.boundaries:
            yield pytest.param(spec, value, id=f"{_ids(spec)}-{value}")


@pytest.mark.parametrize("spec,value", list(_boundary_params()))
def test_t2_boundary_values_roundtrip(spec: Field, value) -> None:
    at = _set(_new_session(), spec, value)
    assert not at.exception
    assert _stored(spec) == value
    assert _widget(_new_session(), spec).value == value


def test_t5_changes_across_consumer_types_are_all_persisted() -> None:
    by_id = {_ids(s): s for s in CONSUMER_FIELDS}
    picks = ["wp-persons_0", "wasch-runs_1", "ev1-ev_cap_2", "pool-rc_set_3"]
    at = _new_session()
    for pick in picks:
        _widget(at, by_id[pick]).set_value(by_id[pick].valid)
    at.run(timeout=_TIMEOUT_S)
    assert not at.exception
    for pick in picks:
        assert _stored(by_id[pick]) == by_id[pick].valid, pick


# --- T3: abgelehnte Eingaben -----------------------------------------------------------

def _consumer_field(entity: str, suffix: str) -> Field:
    return next(s for s in CONSUMER_FIELDS if s.entity == entity and s.suffix == suffix)


@pytest.mark.parametrize(
    "entity,suffix,value",
    [
        pytest.param("pool", "nom_3", 0.0, id="pool-nominal-power-zero"),
        pytest.param("ev1", "ev_min_2", 50.0, id="ev-min-power-above-nominal"),
    ],
)
def test_t3_rejected_value_shows_error_and_keeps_file(entity: str, suffix: str, value: float) -> None:
    spec = _consumer_field(entity, suffix)
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    at = _new_session()
    # Der erste Render normalisiert die Datei per Autosave; erst danach vergleichen.
    before = path.read_bytes()

    at = _set(at, spec, value)

    assert not at.exception
    assert path.read_bytes() == before
    assert at.error, "Ablehnung muss als Fehlermeldung sichtbar sein"
    assert not any("Gespeichert" in c.value for c in at.caption)
