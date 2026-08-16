"""AppTest-Smoketest für Analyse Verbrauch & Kosten (echtes Rendering, headless).

Die Fixture-Config enthält kein Produktiv-Log, daher deckt dieser Test den
Leerzustand ab (Titel + Hinweistexte für Kosten- und Swimspa-Abschnitt).
default_timeout=10 statt der AppTest-Vorgabe (3s): unter voller Test-Suite-
Last kann das Rendering knapp über 3s liegen und sonst spuriös timeouten.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_consumer_analysis.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=10).run()
    assert not at.exception


def test_title_and_empty_state_notice():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=10).run()
    assert at.title[0].value == "📈 Analyse Verbrauch & Kosten"
    assert any(
        "Noch keine Produktiv-Log-Daten" in info.value for info in at.info
    )
