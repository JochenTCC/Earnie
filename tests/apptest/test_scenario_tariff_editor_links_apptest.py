"""Szenarienkonfigurator → Tarife-Seite (Edibert P7 S3): Vorschau über Edibert, Editor-Links."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"
_USER_TARIFF = {
    "id": "user_my_fixed", "label": "Mein Fixtarif", "type": "fixed_cent", "land": "AT",
    "supplier_id": "user_me", "fix_cent_kwh": 24.5, "vat_percent": 20,
}


@pytest.fixture
def switched(monkeypatch):
    """Record page switches instead of switching (the page runs without st.navigation here)."""
    import ui.navigation

    calls: list[str] = []
    monkeypatch.setattr(ui.navigation, "switch_to_page", calls.append)
    return calls


def _write_user_tariffs() -> None:
    user_file = Path(os.environ["EARNIE_TARIFFS_PATH"]).parent / "user_tariffs.json"
    user_file.write_text(
        json.dumps({"tariff_format": 1, "import_tariffs": [_USER_TARIFF], "export_tariffs": []}),
        encoding="utf-8",
    )


def _start() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT), default_timeout=60).run()
    assert not at.exception
    return at


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def test_selected_tariffs_are_previewed_by_edibert():
    at = _start()
    captions = [c.value for c in at.caption]
    assert "Bezugstarif-Vorschau" in captions
    assert "Einspeisetarif-Vorschau" in captions
    assert at.get("arrow_vega_lite_chart") or at.get("vega_lite_chart")
    assert not at.error, [e.value for e in at.error]


def test_manage_button_opens_the_tariffs_page_with_the_scenario_profile(switched):
    from ui.pages.page_tariffs import REQUEST_KEY

    at = _start()
    _button(at, "Benutzertarife verwalten").click().run()
    assert not at.exception
    assert switched == ["tariffs"]
    request = at.session_state[REQUEST_KEY]
    assert request["profile_id"] and request["open"] is None


def test_edit_button_opens_the_selected_user_tariff(switched):
    from ui.pages.page_tariffs import REQUEST_KEY

    _write_user_tariffs()
    at = _start()
    tariff_select = next(sb for sb in at.selectbox if sb.label == "Bezugstarif")
    tariff_select.set_value("Mein Fixtarif · Benutzertarif").run()
    assert not at.exception
    _button(at, "Benutzertarif bearbeiten").click().run()
    assert not at.exception
    assert switched == ["tariffs"]
    assert at.session_state[REQUEST_KEY]["open"] == ("import", "user_my_fixed")


def test_catalog_tariff_has_no_edit_button():
    at = _start()
    assert not [b for b in at.button if b.label == "Benutzertarif bearbeiten"]
