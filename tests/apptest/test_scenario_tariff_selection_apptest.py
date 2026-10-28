"""Tarifauswahl im Szenarienkonfigurator (Edibert P7 S5, Fälle TE1–TE3, TE6 und D6).

Die Auswahl bleibt in Earnie (P7 D1); der Editor-Teil (TE4, Speicherpfad) ist in Edibert getestet.
Szenario ``entity_test`` (Hausprofil ``test_home``, AT): Bezug ``fixed_25ct``, Einspeisung
``monthly_test``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest

from tests.apptest.fields import SCENARIO_ID, SCENARIO_RADIO_LABEL

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"
_TIMEOUT_S = 60.0
_P = f"{SCENARIO_ID}__"
_USER_FIXED_LABEL = "Eigener Festpreis"


def _session(radio_label: str = SCENARIO_RADIO_LABEL) -> AppTest:
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT_S).run()
    at.radio(key="scenario_select").set_value(radio_label).run()
    assert not at.exception
    return at


def _stored_settings(scenario_id: str = SCENARIO_ID) -> dict:
    doc = json.loads(Path(os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"]).read_text(encoding="utf-8"))
    return next(s for s in doc["scenarios"] if s["id"] == scenario_id)["settings"]


def _user_fixed_option(at: AppTest, key: str) -> str:
    return next(o for o in at.selectbox(key=key).options if o.startswith(_USER_FIXED_LABEL))


# --- TE1: filter vs. selection ----------------------------------------------------------


def test_te1_land_filter_keeps_the_saved_tariff_selected():
    at = _session()
    before = at.selectbox(key=_P + "scenario_import").value
    at.selectbox(key=_P + "scenario_tariff_land").set_value("DE").run()
    assert not at.exception
    imports = at.selectbox(key=_P + "scenario_import")
    assert imports.value == before  # never silently replaced by a DE tariff
    assert "DE Spot Test" in imports.options  # the filter applies to the rest of the list
    assert _stored_settings()["import_tariff_id"] == "fixed_25ct"


def test_te1_type_filter_keeps_the_saved_tariff_selected():
    at = _session()
    before = at.selectbox(key=_P + "scenario_import").value
    type_filter = next(
        sb for sb in at.selectbox if sb.key and sb.key.startswith(_P + "scenario_import_filter")
    )
    other = next(o for o in type_filter.options if "Börsenpreis" in o)
    type_filter.set_value(other).run()
    assert not at.exception
    assert at.selectbox(key=_P + "scenario_import").value == before
    assert _stored_settings()["import_tariff_id"] == "fixed_25ct"


# --- TE2: profile switch ----------------------------------------------------------------


def _add_de_profile() -> None:
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    doc = json.loads(path.read_text(encoding="utf-8"))
    profiles = doc["profiles"]
    base = profiles[0] if isinstance(profiles, list) else next(iter(profiles.values()))
    de = {**base, "id": "test_home_de", "label": "Test-Haushalt DE", "land": "DE"}
    if isinstance(profiles, list):
        profiles.append(de)
    else:
        profiles["test_home_de"] = de
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_te2_land_filter_follows_a_new_house_profile():
    _add_de_profile()
    at = _session()
    assert at.selectbox(key=_P + "scenario_tariff_land").value == "AT"
    at.selectbox(key=_P + "scenario_profile").set_value("Test-Haushalt DE").run()
    assert not at.exception
    assert at.selectbox(key=_P + "scenario_tariff_land").value == "DE"


def test_te2_manual_land_filter_stays_while_the_profile_stays():
    at = _session()
    at.selectbox(key=_P + "scenario_tariff_land").set_value("CH").run()
    at.run()
    assert at.selectbox(key=_P + "scenario_tariff_land").value == "CH"


# --- TE3: own fixed price ---------------------------------------------------------------


def test_te3_own_fixed_price_shows_the_default_and_hides_when_deselected():
    at = _session()
    catalog_pick = at.selectbox(key=_P + "scenario_import").value
    assert not [n for n in at.number_input if n.key == _P + "scenario_user_import_cent"]
    at.selectbox(key=_P + "scenario_import").set_value(_user_fixed_option(at, _P + "scenario_import")).run()
    assert not at.exception
    cent = at.number_input(key=_P + "scenario_user_import_cent")
    assert cent.value == 20.0
    cent.set_value(31.5).run()
    settings = _stored_settings()
    assert (settings["import_tariff_id"], settings["user_import_cent_kwh"]) == ("__user_fixed__", 31.5)

    at.selectbox(key=_P + "scenario_import").set_value(catalog_pick).run()
    assert not at.exception
    assert not [n for n in at.number_input if n.key == _P + "scenario_user_import_cent"]
    assert "user_import_cent_kwh" not in _stored_settings()


def test_te3_own_fixed_price_shows_the_saved_value_in_a_new_session():
    at = _session()
    at.selectbox(key=_P + "scenario_import").set_value(_user_fixed_option(at, _P + "scenario_import")).run()
    at.number_input(key=_P + "scenario_user_import_cent").set_value(27.25).run()
    assert _session().number_input(key=_P + "scenario_user_import_cent").value == 27.25


# --- TE6: scenario switch ---------------------------------------------------------------


def test_te6_scenario_switch_keeps_no_values_of_the_previous_scenario():
    other = "Fixture 5 kWh fixe Einspeise"
    reference = _session(other)
    expected = {
        sb.key.removeprefix("fixture_5kwh_fixed__"): sb.value
        for sb in reference.selectbox
        if sb.key and sb.key.startswith("fixture_5kwh_fixed__scenario_")
    }

    at = _session()
    at.selectbox(key=_P + "scenario_tariff_land").set_value("CH").run()
    at.selectbox(key=_P + "scenario_import").set_value(_user_fixed_option(at, _P + "scenario_import")).run()
    at.radio(key="scenario_select").set_value(other).run()
    assert not at.exception
    shown = {
        sb.key.removeprefix("fixture_5kwh_fixed__"): sb.value
        for sb in at.selectbox
        if sb.key and sb.key.startswith("fixture_5kwh_fixed__scenario_")
    }
    assert shown == expected
    assert not [n for n in at.number_input if n.key and n.key.endswith("scenario_user_import_cent")]


# --- D6: next-month rate of a user monthly tariff ---------------------------------------

_USER_MONTHLY = {
    "id": "user_monatlich", "label": "Mein Monatstarif", "type": "monthly_table", "land": "AT",
    "supplier_id": "user_me", "vat_percent": 0,
    "monthly_rates": [{"year": 2026, "month": m, "tariff_cent_kwh": 8.0} for m in range(1, 11)],
}


def test_next_month_warning_of_a_user_tariff_opens_the_editor(monkeypatch):
    import ui.navigation
    from ui.pages import page_scenario_editor
    from ui.pages.page_tariffs import REQUEST_KEY

    Path(os.environ["EARNIE_TARIFFS_PATH"]).with_name("user_tariffs.json").write_text(
        json.dumps({"tariff_format": 1, "import_tariffs": [], "export_tariffs": [_USER_MONTHLY]}),
        encoding="utf-8",
    )
    month_end = datetime(2026, 10, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna"))
    monkeypatch.setattr(page_scenario_editor, "_planning_now", lambda: month_end)
    switched: list[str] = []
    monkeypatch.setattr(ui.navigation, "switch_to_page", switched.append)

    at = _session()
    at.selectbox(key=_P + "scenario_export").set_value("Mein Monatstarif · Benutzertarif").run()
    assert not at.exception
    assert any("Mein Monatstarif" in w.value and "2026-11" in w.value for w in at.warning)
    assert not [n for n in at.number_input if n.key == _P + "next_month_cent_export"]
    at.button(key=_P + "next_month_editor_export").click().run()
    assert not at.exception
    assert switched == ["tariffs"]
    assert at.session_state[REQUEST_KEY]["open"] == ("export", "user_monatlich")
