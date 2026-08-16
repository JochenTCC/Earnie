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
