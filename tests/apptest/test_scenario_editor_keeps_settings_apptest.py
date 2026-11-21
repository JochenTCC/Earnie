"""Szenarienkonfigurator: open and save keep what the form does not show (UI review slice 4c).

- Opening a scenario writes nothing; settings the form does not show (flat overrides such as
  ``pv_kwp``) survive a save.
- References to entries that do not exist (deleted tariff) stay until the user removes them.
- An unsaveable form asks before switching, and the discard button switches.
- A deleted scenario's id can be created again.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"
_TIMEOUT_S = 30.0
_FLAT = "fixture_5kwh_fixed"
_FLAT_RADIO = "Fixture 5 kWh fixe Einspeise"
_ENTITY = "entity_test"
_ENTITY_RADIO = "Entitäten-Referenzen Test"
_NEW_OPTION = "— neu —"


def _path() -> Path:
    return Path(os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"])


def _stored() -> dict:
    return {s["id"]: s for s in json.loads(_path().read_text(encoding="utf-8"))["scenarios"]}


def _session(radio_label: str) -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    at.radio(key="scenario_select").set_value(radio_label).run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def test_opening_a_scenario_with_flat_overrides_writes_nothing():
    before = _stored()[_FLAT]
    at = _session(_FLAT_RADIO)
    at.run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert _stored()[_FLAT] == before


def test_saving_a_scenario_keeps_settings_the_form_does_not_show():
    before = _stored()[_FLAT]["settings"]
    at = _session(_FLAT_RADIO)
    at.text_input(key=f"{_FLAT}__scenario_label").set_value("Flach geändert").run(timeout=_TIMEOUT_S)
    assert not at.exception
    stored = _stored()[_FLAT]
    assert stored["label"] == "Flach geändert"
    for key in ("pv_kwp", "battery_capacity_kwh", "latitude", "timezone_name", "threshold_power"):
        assert stored["settings"][key] == before[key]


def _with_deleted_import_tariff() -> None:
    doc = json.loads(_path().read_text(encoding="utf-8"))
    for scenario in doc["scenarios"]:
        if scenario["id"] == _ENTITY:
            scenario["settings"]["import_tariff_id"] = "deleted_tariff"
    _path().write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_reference_to_a_deleted_tariff_stays_until_removed():
    _with_deleted_import_tariff()
    at = _session(_ENTITY_RADIO)
    at.run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert _stored()[_ENTITY]["settings"]["import_tariff_id"] == "deleted_tariff"
    assert any("deleted_tariff" in w.value for w in at.warning)

    at.button(key=f"{_ENTITY}__scenario_drop_missing_refs").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert "import_tariff_id" not in _stored()[_ENTITY]["settings"]


def test_editing_a_scenario_with_a_deleted_tariff_keeps_the_reference():
    _with_deleted_import_tariff()
    at = _session(_ENTITY_RADIO)
    at.text_input(key=f"{_ENTITY}__scenario_label").set_value("Mit Lücke").run(timeout=_TIMEOUT_S)
    assert not at.exception
    stored = _stored()[_ENTITY]
    assert stored["label"] == "Mit Lücke"
    assert stored["settings"]["import_tariff_id"] == "deleted_tariff"


def test_unsaveable_form_asks_before_switching_and_discard_switches():
    at = _session(_ENTITY_RADIO)
    # An empty label cannot be saved: the edit stays in the form.
    at.text_input(key=f"{_ENTITY}__scenario_label").set_value("").run(timeout=_TIMEOUT_S)
    at.radio(key="scenario_select").set_value(_FLAT_RADIO).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert any("ungespeicherte Änderungen" in w.value for w in at.warning)
    at.button(key="scenario_switch_discard").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert at.session_state["scenario_editor_active_select"] == _FLAT
    assert _stored()[_ENTITY]["label"] == _ENTITY_RADIO


def test_new_scenario_is_saved_again_after_deleting_the_same_one():
    at = _session(_ENTITY_RADIO)
    ids_before = set(_stored())
    at.radio(key="scenario_select").set_value(_NEW_OPTION).run(timeout=_TIMEOUT_S)
    assert not at.exception
    created = set(_stored()) - ids_before
    assert len(created) == 1
    new_id = created.pop()
    at.run(timeout=_TIMEOUT_S)
    assert at.session_state["scenario_editor_active_select"] == new_id
    at.button(key="scenario_delete").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert new_id not in _stored()

    # Template source is the scenario selected last: pick entity_test again, then "— neu —".
    at.radio(key="scenario_select").set_value(_ENTITY_RADIO).run(timeout=_TIMEOUT_S)
    at.radio(key="scenario_select").set_value(_NEW_OPTION).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert new_id in _stored()
