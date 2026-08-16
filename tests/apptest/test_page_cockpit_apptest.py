"""AppTest-Smoketest für das Monitor-Cockpit (echtes Rendering, headless).

Läuft offline (EARNIE_OFFLINE=1, kein LOXONE_IP) — Loxone-Live-Abfragen
schlagen daher schnell fehl statt zu blockieren; die Seite fängt das ab und
zeigt den Cockpit-Rahmen (Titel, Savings-Chart, Sankey, Countdown) ohne
Live-Werte.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_cockpit.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_present():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "🔋 Monitor"
