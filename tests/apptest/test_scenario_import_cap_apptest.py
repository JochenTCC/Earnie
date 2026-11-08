"""Scenario editor: the import cap is stored, cleared, refused and explained."""
from __future__ import annotations

import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.apptest.fields import SCENARIO_ID, SCENARIO_RADIO_LABEL

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"
_TIMEOUT_S = 60.0
_CAP = f"{SCENARIO_ID}__scenario_import_cap"
_MARGIN = f"{SCENARIO_ID}__scenario_import_cap_margin"
_PROFILE = f"{SCENARIO_ID}__scenario_profile"


def _session() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT_S).run()
    at.radio(key="scenario_select").set_value(SCENARIO_RADIO_LABEL).run()
    assert not at.exception
    return at


def _stored() -> dict:
    doc = json.loads(Path(os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"]).read_text(encoding="utf-8"))
    return next(s for s in doc["scenarios"] if s["id"] == SCENARIO_ID)["settings"]


def _add_capacity_charge(**overrides) -> None:
    path = Path(os.environ["EARNIE_GRID_FEES_PATH"]).parent / "user_grid_fees.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    area = next(item for item in doc["areas"] if item["id"] == "user_test_home")
    area["capacity_charges"] = [
        {
            "id": "lp",
            "basis": "monthly_peak_15min",
            "min_kw": 2.0,
            "bands": [{"up_to_kw": None, "cent_per_kw_month": 150}],
            **overrides,
        }
    ]
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_without_a_cap_nothing_is_stored():
    at = _session()
    assert at.number_input(key=_CAP).value is None
    assert at.number_input(key=_MARGIN).value == 0.3
    assert at.number_input(key=_MARGIN).disabled
    assert "import_cap_kw" not in _stored()
    assert "import_cap_margin_kw" not in _stored()


def test_cap_is_stored_with_the_proposed_margin_and_survives_a_new_session():
    at = _session()
    at.number_input(key=_CAP).set_value(5.0).run()
    assert not at.exception
    assert _stored()["import_cap_kw"] == 5.0
    assert _stored()["import_cap_margin_kw"] == 0.3
    again = _session()
    assert again.number_input(key=_CAP).value == 5.0
    assert not again.number_input(key=_MARGIN).disabled


def test_margin_change_is_stored():
    at = _session()
    at.number_input(key=_CAP).set_value(5.0).run()
    at.number_input(key=_MARGIN).set_value(0.5).run()
    assert not at.exception
    assert _stored()["import_cap_margin_kw"] == 0.5


def test_clearing_the_cap_removes_both_keys():
    at = _session()
    at.number_input(key=_CAP).set_value(5.0).run()
    at.number_input(key=_CAP).set_value(None).run()
    assert not at.exception
    assert "import_cap_kw" not in _stored()
    assert "import_cap_margin_kw" not in _stored()


def test_margin_not_below_the_cap_is_refused_and_not_stored():
    at = _session()
    at.number_input(key=_MARGIN)  # enabled once a cap is set
    at.number_input(key=_CAP).set_value(5.0).run()
    at.number_input(key=_MARGIN).set_value(5.0).run()
    assert not at.exception
    assert any("kleiner als" in item.value for item in at.error)
    assert _stored()["import_cap_margin_kw"] == 0.3


def test_cap_without_house_profile_is_refused_and_not_stored():
    at = _session()
    at.selectbox(key=_PROFILE).set_value("— keine —").run()
    before = _stored()
    at.number_input(key=_CAP).set_value(5.0).run()
    assert not at.exception
    assert any("Netzbereich" in item.value for item in at.error)
    assert _stored() == before


def test_area_without_charge_says_inactive_and_still_stores():
    at = _session()
    at.number_input(key=_CAP).set_value(5.0).run()
    assert any("inaktiv" in item.value for item in at.info)
    assert _stored()["import_cap_kw"] == 5.0


def test_cap_below_the_minimum_is_refused_and_not_stored():
    _add_capacity_charge()
    at = _session()
    at.number_input(key=_CAP).set_value(1.5).run()
    assert not at.exception
    assert any("Mindestleistung" in item.value for item in at.error)
    assert "import_cap_kw" not in _stored()


def test_future_charge_names_the_start():
    _add_capacity_charge(valid_from="2099-01-01")
    at = _session()
    at.number_input(key=_CAP).set_value(5.0).run()
    assert any("inaktiv bis 01/2099" in item.value for item in at.info)
    assert _stored()["import_cap_kw"] == 5.0


def test_stored_cap_does_not_mark_the_form_as_edited():
    at = _session()
    at.number_input(key=_CAP).set_value(5.0).run()
    at = _session()
    labels = at.radio(key="scenario_select").options
    other = next(option for option in labels if option != SCENARIO_RADIO_LABEL)
    at.radio(key="scenario_select").set_value(other).run()
    assert not at.exception
    assert not [button for button in at.button if button.key == "scenario_switch_cancel"]
