"""AppTest-Smoketest für den Roh-JSON-Konfigurationseditor (echtes Rendering, headless)."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_config.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_and_editor_present():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "⚙️ Konfiguration"
    [editor] = at.text_area
    assert editor.value.strip().startswith("{")


def test_validate_button_reports_success():
    at = AppTest.from_file(str(_SCRIPT)).run()
    validate_button = next(b for b in at.button if b.label == "Validieren")
    validate_button.click().run()
    assert not at.exception
    assert any(
        success.value == "JSON und Schema sind gültig." for success in at.success
    )


def test_reload_button_restores_file_content():
    """Regression: reload used to set the editor key after the text_area ran
    (StreamlitWidgetAlreadyInstantiatedError)."""
    at = AppTest.from_file(str(_SCRIPT)).run()
    file_text = at.text_area[0].value
    at.text_area[0].set_value('{"edited": true}').run()
    at.button(key="config_reload").click().run()
    assert not at.exception
    assert at.text_area[0].value == file_text


def test_reload_button_reports_unreadable_file(monkeypatch):
    from ui.pages import page_config

    at = AppTest.from_file(str(_SCRIPT)).run()

    def _unreadable(_path):
        raise ValueError("kaputt")

    monkeypatch.setattr(page_config, "_read_config_text", _unreadable)
    at.button(key="config_reload").click().run()
    assert not at.exception
    assert any("kaputt" in err.value for err in at.error)
