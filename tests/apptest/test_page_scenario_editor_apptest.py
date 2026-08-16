"""AppTest-Smoketests für den Szenarienkonfigurator (echtes Rendering, headless)."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_and_scenario_selects_present():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "🧪 Szenarienkonfigurator"
    labels = {sb.label for sb in at.selectbox}
    assert "Hausprofil" in labels
    assert "Bezugstarif" in labels
    assert "Einspeisetarif" in labels


def test_switch_import_tariff_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    tarif_select = next(sb for sb in at.selectbox if sb.label == "Bezugstarif")
    options = tarif_select.options
    other_option = next((o for o in options if o != tarif_select.value), None)
    if other_option is None:
        return
    tarif_select.set_value(other_option).run()
    assert not at.exception
