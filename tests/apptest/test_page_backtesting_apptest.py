"""AppTest-Smoketest für den Szenario-Explorer (echtes Rendering, headless).

Die Fixture-Config unter tests/fixtures/backtesting/ enthält keinen
Szenario-Explorer-Log, daher deckt dieser Test den Leerzustand ab (Titel,
Hinweistext, Run-Controls) — kein Backtesting-Lauf wird ausgelöst.
Open-Meteo ist für den ganzen AppTest über tests/apptest/conftest.py gemockt
(cons_data modeled-PV würde sonst archive-api.open-meteo.com anrufen).
default_timeout=30 statt der AppTest-Vorgabe (3s, zwischenzeitlich 10s):
unter voller Test-Suite-Last (parallele MILP-/Backtesting-Rechentests) UND
mit `pytest --cov=.` (Coverage-Instrumentierung verlangsamt den Script-Run
durch den zusätzlichen Trace-Overhead spürbar) lag das Rendering in CI
wiederholt über 10s und ließ die Tests spuriös timeouten.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_backtesting.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=30).run()
    assert not at.exception


def test_title_and_empty_state_notice():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=30).run()
    assert at.title[0].value == "📊 Szenario-Explorer"
    assert any(
        "Noch kein Szenario-Explorer-Lauf vorhanden" in info.value for info in at.info
    )


_ACTIVE_RUN_SCRIPT = Path(__file__).parent / "scripts" / "run_backtesting_active_run.py"


def _active_run(exit_code: int, cancel_requested: bool) -> AppTest:
    at = AppTest.from_file(str(_ACTIVE_RUN_SCRIPT), default_timeout=30)
    at.session_state["_fake_run_cfg"] = {"exit_code": exit_code, "cancel_requested": cancel_requested}
    return at.run()


def test_cancelled_run_of_the_session_shows_the_cancel_notice():
    at = _active_run(130, cancel_requested=True)
    assert not at.exception
    assert any("abgebrochen" in info.value for info in at.info)
    cancel = [b for b in at.button if b.key == "backtesting_cancel_btn"]
    assert cancel and cancel[0].disabled
    assert "_backtesting_active_run" not in at.session_state


def test_failed_run_is_not_reported_as_cancelled():
    at = _active_run(130, cancel_requested=False)
    assert not at.exception
    assert not any("abgebrochen" in info.value for info in at.info)
    assert any("Exit-Code 130" in err.value for err in at.error)
