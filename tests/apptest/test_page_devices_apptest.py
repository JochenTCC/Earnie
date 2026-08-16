"""AppTest-Smoketest für Manuelle Geräte (echtes Rendering, headless).

Die Fixture-Hausprofile enthalten keinen manuellen (earnie_role: manual)
Verbraucher, daher deckt dieser Test den Leerzustand ab (Titel + Hinweis).
Eine tiefere Interaktion (Empfehlungstabelle, Plan-Checkbox) bräuchte
zusätzlich einen persistierten main.py-Snapshot (live_display_loader) —
bewusst als möglicher Ausbauschritt offen gelassen.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_devices.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_and_empty_state_notice():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "🔌 Manuelle Geräte"
    assert any("Keine manuellen Geräte konfiguriert" in info.value for info in at.info)
