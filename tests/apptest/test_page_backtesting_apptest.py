"""AppTest-Smoketest für den Szenario-Explorer (echtes Rendering, headless).

Die Fixture-Config unter tests/fixtures/backtesting/ enthält keinen
Szenario-Explorer-Log, daher deckt dieser Test den Leerzustand ab (Titel,
Hinweistext, Run-Controls) — kein Backtesting-Lauf wird ausgelöst.
default_timeout=10 statt der AppTest-Vorgabe (3s): unter voller Test-Suite-
Last (parallele MILP-/Backtesting-Rechentests) kann das Rendering knapp
über 3s liegen und sonst spuriös timeouten.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_backtesting.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=10).run()
    assert not at.exception


def test_title_and_empty_state_notice():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=10).run()
    assert at.title[0].value == "📊 Szenario-Explorer"
    assert any(
        "Noch kein Szenario-Explorer-Lauf vorhanden" in info.value for info in at.info
    )
