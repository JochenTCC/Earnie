"""Ebene 2 (Playwright): kritische Pfade im echten Browser - T6, T7, T9, D9.

Die Persistenzpfade laufen über das Bezeichnungsfeld des Szenarienkonfigurators; der
Hauskonfigurator ist wegen eines Browser-Fehlers (siehe
``test_house_config_first_edit_after_open_is_kept``) dafür nicht zuverlässig nutzbar.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.apptest.e2e.conftest import AppServer
from tests.apptest.states import MIXED_LOG

_TIMEOUT_MS = 60_000
_SCENARIO_ID = "entity_test"
_SCENARIO_RADIO_LABEL = "Entitäten-Referenzen Test"
_NEW_LABEL = "Gespeichert im Browser – Ünï 日本"


def _wait_until_idle(page: Page) -> None:
    """Wartet, bis kein Skriptlauf mehr aktiv ist (Streamlit blendet dann das Status-Widget aus).

    Eingaben während eines laufenden Durchlaufs können vom Rerun überschrieben werden; der
    Ruhezustand muss deshalb eine Sekunde anhalten.
    """
    status = page.locator("[data-testid='stStatusWidget']")
    for _ in range(2):
        expect(status).to_have_count(0, timeout=_TIMEOUT_MS)
        page.wait_for_timeout(1000)
    expect(status).to_have_count(0, timeout=_TIMEOUT_MS)


def _type_and_commit(page: Page, field: Locator, text: str) -> None:
    field.click()
    field.press("Control+a")
    field.type(text)
    expect(field).to_have_value(text)
    field.press("Enter")  # Streamlit übernimmt erst bei Enter/Blur
    _wait_until_idle(page)


def _go_to(page: Page, title: str) -> None:
    page.locator("[data-testid='stSidebarNav'] a", has_text=title).click()


# --- Szenarienkonfigurator: Bezeichnung -------------------------------------------------


def _label_input(page: Page) -> Locator:
    return page.locator(f".st-key-{_SCENARIO_ID}__scenario_label input")


def _select_scenario(page: Page, radio_label: str) -> None:
    page.locator(".st-key-scenario_select label", has_text=radio_label).click()
    _wait_until_idle(page)
    expect(_label_input(page)).to_be_visible(timeout=_TIMEOUT_MS)


def _open_scenario_editor(page: Page, server: AppServer) -> None:
    page.goto(f"{server.url}/scenario-editor")
    expect(page.locator(".st-key-scenario_select")).to_be_visible(timeout=_TIMEOUT_MS)
    _wait_until_idle(page)
    _select_scenario(page, _SCENARIO_RADIO_LABEL)


def _stored_label() -> str:
    path = Path(os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"])
    scenarios = json.loads(path.read_text(encoding="utf-8"))["scenarios"]
    return next(s for s in scenarios if s["id"] == _SCENARIO_ID)["label"]


def _wait_until_stored(page: Page, expected: str, timeout_s: float = 30.0) -> None:
    waited = 0.0
    while _stored_label() != expected:
        assert waited < timeout_s, f"Bezeichnung nicht gespeichert (aktuell {_stored_label()!r})"
        page.wait_for_timeout(250)
        waited += 0.25


def _save_new_label(page: Page) -> None:
    _type_and_commit(page, _label_input(page), _NEW_LABEL)
    _wait_until_stored(page, _NEW_LABEL)


def _reopen_scenario_editor_with_new_label(page: Page, url: str) -> None:
    page.goto(url)
    expect(page.locator(".st-key-scenario_select")).to_be_visible(timeout=_TIMEOUT_MS)
    _wait_until_idle(page)
    _select_scenario(page, _NEW_LABEL)


def test_t6_value_survives_page_switch_and_back(page: Page, app_server: AppServer) -> None:
    _open_scenario_editor(page, app_server)
    _save_new_label(page)

    _go_to(page, "Hauskonfigurator")
    expect(page.locator(".st-key-test_home__house_annual_kwh")).to_be_visible(timeout=_TIMEOUT_MS)
    _go_to(page, "Szenarienkonfigurator")
    expect(page.locator(".st-key-scenario_select")).to_be_visible(timeout=_TIMEOUT_MS)
    _wait_until_idle(page)
    _select_scenario(page, _NEW_LABEL)

    expect(_label_input(page)).to_have_value(_NEW_LABEL)


def test_t7_value_survives_browser_reload(page: Page, app_server: AppServer) -> None:
    _open_scenario_editor(page, app_server)
    _save_new_label(page)

    _reopen_scenario_editor_with_new_label(page, page.url)

    expect(_label_input(page)).to_have_value(_NEW_LABEL)


def test_t9_value_survives_app_restart(page: Page, app_server: AppServer) -> None:
    _open_scenario_editor(page, app_server)
    _save_new_label(page)

    app_server.restart()
    _reopen_scenario_editor_with_new_label(page, f"{app_server.url}/scenario-editor")

    expect(_label_input(page)).to_have_value(_NEW_LABEL)


# --- Hauskonfigurator: erste Eingabe nach dem Öffnen -------------------------------------

# Früher Browser-only-Fehler in ca. 60 % der Öffnungen (Auswahl sprang auf "— neu —"),
# daher mehrere Versuche: Ein Zufallstreffer bei einem Rückfall ist unter 1 %.
_HOUSE_ATTEMPTS = 6


def test_house_config_first_edit_after_open_is_kept(page: Page, app_server: AppServer) -> None:
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    annual = page.locator(".st-key-test_home__house_annual_kwh input")
    for attempt in range(_HOUSE_ATTEMPTS):
        page.goto(f"{app_server.url}/house-config")
        expect(annual).to_be_visible(timeout=_TIMEOUT_MS)
        _wait_until_idle(page)
        _type_and_commit(page, annual, str(5000 + attempt))
        page.wait_for_timeout(1500)
        profiles = json.loads(path.read_text(encoding="utf-8"))["profiles"]
        assert [p["id"] for p in profiles] == ["test_home"], "unerwartet angelegtes Profil"
        assert next(p for p in profiles if p["id"] == "test_home")["annual_kwh"] == 5000 + attempt


# --- D9: Log-Filter im Fragment-Refresh --------------------------------------------------

_FRAGMENT_REFRESH_S = 10


def test_d9_log_filter_and_open_expander_survive_fragment_refresh(
    page: Page, app_server_with_hub: AppServer, log_file
) -> None:
    server = app_server_with_hub
    log_file(MIXED_LOG)
    page.goto(f"{server.url}/optimizer-daemon")
    expander = page.locator(".st-key-daemon_log_expander")
    expect(expander).to_be_visible(timeout=_TIMEOUT_MS)
    _wait_until_idle(page)
    expander.get_by_text("earnie.log").first.click()
    levels = page.locator(".st-key-daemon_log_levels")
    expect(levels).to_be_visible(timeout=_TIMEOUT_MS)
    levels.get_by_role("button", name="Remove INFO").click()
    _wait_until_idle(page)
    expect(page.get_by_text("Anzeige: 5 von 8 Zeilen (Level-Filter).")).to_be_visible()

    # Neue Zeile schreiben und den Auto-Refresh des Fragments abwarten: sie erscheint nur,
    # wenn das Fragment neu gelaufen ist; der Filter muss dabei erhalten bleiben.
    log_file.path.write_text(
        MIXED_LOG + "\n2026-10-22 10:00:06 [ERROR] nach dem Refresh\n", encoding="utf-8"
    )
    expect(page.get_by_text("nach dem Refresh")).to_be_visible(
        timeout=(_FRAGMENT_REFRESH_S + 15) * 1000
    )

    expect(levels.get_by_role("button", name="Remove INFO")).to_have_count(0)
    expect(page.get_by_text("Anzeige: 6 von 9 Zeilen (Level-Filter).")).to_be_visible()
    expect(levels).to_be_visible()  # Expander ist noch offen
