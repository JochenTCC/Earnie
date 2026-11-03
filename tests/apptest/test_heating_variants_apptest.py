"""Heating-system variants: scenario select box (Szenarienkonfigurator) and variants editor
(Hauskonfigurator, area "Heizsysteme").

The fixture house ``test_home`` has the thermal_annual consumer ``wp`` with its reference
system ``heating_test_home``; each test adds a gas variant to the isolated components.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.apptest.fields import SCENARIO_ID, SCENARIO_RADIO_LABEL

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"
_HOUSE_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_PICK_KEY = f"{SCENARIO_ID}__scenario_heating_wp"
_GAS = {"id": "gas_variante", "label": "Gas-Variante", "heat_source": {"type": "gas"}}


def _components_path() -> Path:
    return Path(os.environ["EARNIE_COMPONENTS_PATH"])


def _catalog() -> list[dict]:
    return json.loads(_components_path().read_text(encoding="utf-8"))["heating_systems"]


def _scenario(scenario_id: str = SCENARIO_ID) -> dict:
    path = os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"]
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    return next(s for s in doc["scenarios"] if s["id"] == scenario_id)


@pytest.fixture(autouse=True)
def _gas_variant():
    from house_config.components_store import clear_components_doc_cache
    from house_config.profiles_store import clear_house_profiles_doc_cache
    from tests.conftest import _reinit_config_offline

    doc = json.loads(_components_path().read_text(encoding="utf-8"))
    doc["heating_systems"].append(dict(_GAS))
    _components_path().write_text(json.dumps(doc), encoding="utf-8")
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()
    _reinit_config_offline()


def _session(radio_label: str = SCENARIO_RADIO_LABEL) -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    at.radio(key="scenario_select").set_value(radio_label).run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def _editor_session() -> AppTest:
    at = AppTest.from_file(str(_HOUSE_SCRIPT)).run(timeout=_TIMEOUT_S)
    at.segmented_control[0].set_value("Heizsysteme").run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def test_scenario_editor_has_no_variants_editor() -> None:
    at = _session()
    assert not [sb for sb in at.selectbox if sb.key == "hsv_select"]


def test_scenario_select_defaults_to_the_reference_system() -> None:
    at = _session()
    pick = at.selectbox(key=_PICK_KEY)
    assert pick.value.endswith("(Referenzsystem)")
    assert "Gas-Variante" in pick.options
    assert "heating_system_ids" not in _scenario()["settings"]


def test_scenario_variant_pick_is_saved_and_reseeded() -> None:
    at = _session()
    at.selectbox(key=_PICK_KEY).set_value("Gas-Variante").run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert _scenario()["settings"]["heating_system_ids"] == {"wp": "gas_variante"}
    assert _session().selectbox(key=_PICK_KEY).value == "Gas-Variante"

    at = _session()
    reference = next(o for o in at.selectbox(key=_PICK_KEY).options if "Referenzsystem" in o)
    at.selectbox(key=_PICK_KEY).set_value(reference).run(timeout=_TIMEOUT_S)
    assert "heating_system_ids" not in _scenario()["settings"]


def test_scenario_with_variant_switches_to_other_scenarios() -> None:
    """A saved variant pick is no unsaved edit: switching to Live and to „— neu —“ works."""
    at = _session()
    at.selectbox(key=_PICK_KEY).set_value("Gas-Variante").run(timeout=_TIMEOUT_S)
    assert _scenario()["settings"]["heating_system_ids"] == {"wp": "gas_variante"}

    at = _session()
    at.radio(key="scenario_select").set_value("Live").run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert at.radio(key="scenario_select").value == "Live"

    at = _session()
    at.radio(key="scenario_select").set_value("— neu —").run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert at.radio(key="scenario_select").value not in ("— neu —", SCENARIO_RADIO_LABEL)


def test_live_scenario_names_the_reference_system_without_select() -> None:
    at = _session("Live")
    assert not [sb for sb in at.selectbox if "scenario_heating_wp" in str(sb.key)]
    label = next(e["label"] for e in _catalog() if e["id"] == "heating_test_home")
    line = f"Heizsystem: {label} (Referenzsystem, Änderung im Hauskonfigurator)"
    assert line in [m.value for m in at.markdown]


def test_scenario_select_offers_no_other_houses_reference_system() -> None:
    from house_config.components_store import clear_components_doc_cache
    from house_config.profiles_store import clear_house_profiles_doc_cache

    doc = json.loads(_components_path().read_text(encoding="utf-8"))
    other_entry = {**doc["heating_systems"][0], "id": "heating_other", "label": "WP Nachbar"}
    doc["heating_systems"].append(other_entry)
    _components_path().write_text(json.dumps(doc), encoding="utf-8")
    house_path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    house = json.loads(house_path.read_text(encoding="utf-8"))
    other = json.loads(json.dumps(house["profiles"][0]))
    other.update(id="nachbar", label="Nachbarhaus")
    for consumer in other["consumers"]:
        if consumer.get("type") == "thermal_annual":
            consumer["heating_system_id"] = "heating_other"
    house["profiles"].append(other)
    house_path.write_text(json.dumps(house, ensure_ascii=False), encoding="utf-8")
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()

    options = _session().selectbox(key=_PICK_KEY).options
    assert "WP Nachbar" not in options
    assert "Gas-Variante" in options
    assert sum("(Referenzsystem)" in o for o in options) == 1


def test_reference_system_is_read_only_and_can_be_copied() -> None:
    at = _editor_session()
    reference = next(o for o in at.selectbox(key="hsv_select").options if "Referenzsystem" in o)
    at.selectbox(key="hsv_select").set_value(reference).run(timeout=_TIMEOUT_S)
    assert any("nur lesbar" in i.value for i in at.info)
    assert not [b for b in at.button if str(b.key).endswith("__save")]
    at.button(key="hsv_copy").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    copies = [e for e in _catalog() if e["label"].endswith("(Kopie)")]
    assert len(copies) == 1
    assert copies[0]["heat_source"] == {"type": "heat_pump", "heat_pump_type": "luft"}
    assert at.selectbox(key="hsv_select").value == copies[0]["label"]


def test_variant_edit_and_delete_guard() -> None:
    at = _editor_session()
    at.selectbox(key="hsv_select").set_value("Gas-Variante").run(timeout=_TIMEOUT_S)
    label_key = next(t.key for t in at.text_input if str(t.key).endswith("__label"))
    at.text_input(key=label_key).set_value("Gas neu").run(timeout=_TIMEOUT_S)
    save_key = next(b.key for b in at.button if str(b.key).endswith("__save"))
    at.button(key=save_key).click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert next(e for e in _catalog() if e["id"] == "gas_variante")["label"] == "Gas neu"

    # Referenced by a scenario → delete refused, entry stays.
    _session().selectbox(key=_PICK_KEY).set_value("Gas neu").run(timeout=_TIMEOUT_S)
    at = _editor_session()
    at.selectbox(key="hsv_select").set_value("Gas neu").run(timeout=_TIMEOUT_S)
    delete_key = next(b.key for b in at.button if str(b.key).endswith("__delete"))
    at.button(key=delete_key).click().run(timeout=_TIMEOUT_S)
    assert any("wird noch verwendet" in e.value for e in at.error)
    assert any(e["id"] == "gas_variante" for e in _catalog())
