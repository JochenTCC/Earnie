"""Planning forms from the ui slice 2 review, package 2d (battery, wallbox)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from house_config.components_store import (
    clear_components_doc_cache,
    load_components_document,
)
from tests.apptest.fields import WALLBOX_ID
from tests.fixtures.ev_wallbox import merge_wallboxes, wallbox_entry

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_BAT = "test_battery"


@pytest.fixture(autouse=True)
def _components_with_wallbox(_isolated_backtesting_config):
    path = os.environ["EARNIE_COMPONENTS_PATH"]
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(merge_wallboxes(doc, [wallbox_entry(WALLBOX_ID)]), handle, ensure_ascii=False)
    clear_components_doc_cache()


def _doc() -> dict:
    clear_components_doc_cache()
    return load_components_document(os.environ["EARNIE_COMPONENTS_PATH"])


def _battery() -> dict:
    return next(b for b in _doc()["batteries"] if b["id"] == _BAT)


def _session(tab: str) -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    at.segmented_control[0].set_value(tab).run(timeout=_TIMEOUT_S)
    return _ok(at)


def _ok(at: AppTest) -> AppTest:
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    return at


def _key(suffix: str) -> str:
    return f"{_BAT}__{suffix}"


def test_hidden_wear_fields_keep_their_values():
    """2d-1: re-ticking Verschleiß brought back 0.01 € / 1 cycle and saved them."""
    at = _session("Batterien")
    at.checkbox(key=_key("planning_battery_wear_enabled")).check().run(timeout=_TIMEOUT_S)
    at.number_input(key=_key("planning_battery_wear_replacement_cost")).set_value(2345.0)
    at.number_input(key=_key("planning_battery_wear_expected_cycles")).set_value(7000.0)
    _ok(at.run(timeout=_TIMEOUT_S))
    at.checkbox(key=_key("planning_battery_wear_enabled")).uncheck().run(timeout=_TIMEOUT_S)
    assert _battery()["battery_wear"]["enabled"] is False
    _ok(at.checkbox(key=_key("planning_battery_wear_enabled")).check().run(timeout=_TIMEOUT_S))
    wear = _battery()["battery_wear"]
    assert wear["enabled"] is True
    assert wear["replacement_cost_euro"] == pytest.approx(2345.0)
    assert wear["expected_cycles"] == pytest.approx(7000.0)


def test_house_battery_becomes_a_physical_powerstation():
    """2d-2: stored regulates_on blocked the switch; 2d-3: the new inverter kept η 0.97."""
    from house_config.inverter import DEFAULT_INVERTER_EFFICIENCY

    at = _session("Batterien")
    at.selectbox(key=_key("planning_battery_type")).set_value("Powerstation")
    # Backing starts at Virtuell, which needs a second house battery: refused, no write.
    at.run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not any("regulates_on" in e.value for e in at.error)
    assert _battery()["type"] == "house"
    at.selectbox(key=_key("planning_battery_backing")).set_value("Physisch")
    _ok(at.run(timeout=_TIMEOUT_S))
    _ok(at.run(timeout=_TIMEOUT_S))
    battery = _battery()
    assert battery["type"] == "powerstation"
    assert battery["backing"] == "physical"
    assert "regulates_on" not in battery
    inverter = next(i for i in _doc()["inverters"] if i["id"] == battery["inverter_id"])
    assert inverter["owned_by"] == _BAT
    assert inverter["efficiency"] == pytest.approx(DEFAULT_INVERTER_EFFICIENCY)
    assert str(inverter["label"]).strip()
    assert at.text_input(key=_key("planning_bat_inv_label")).value == inverter["label"]


def test_deleting_the_last_wallbox_does_not_recreate_one():
    """2d-6: the "— neu —" draft after the delete auto-saved a default wallbox."""
    at = _session("Wallboxen")
    at.button(key="planning_wb_delete").click().run(timeout=_TIMEOUT_S)
    _ok(at.run(timeout=_TIMEOUT_S))
    assert not _doc().get("wallboxes")
