"""AppTest-Smoketests für den Hauskonfigurator (echtes Rendering, headless).

AppTest.from_function() führt nur den Funktions-Body ohne Modul-Imports aus
(NameError auf importierte Namen) — daher zeigt jedes Test-Skript unter
tests/apptest/scripts/ per from_file() auf die echte render()-Funktion.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_and_default_tab():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "🏠 Hauskonfigurator"
    [tabs] = at.segmented_control
    assert tabs.options == ["Hausprofil", "PV-Anlagen", "Batterien"]
    assert tabs.value == "Hausprofil"


def test_switch_to_pv_tab_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    [tabs] = at.segmented_control
    tabs.set_value("PV-Anlagen").run()
    assert not at.exception
    [tabs_after] = at.segmented_control
    assert tabs_after.value == "PV-Anlagen"


def test_switch_to_batterien_tab_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    [tabs] = at.segmented_control
    tabs.set_value("Batterien").run()
    assert not at.exception
