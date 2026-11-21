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
    # The page reruns once the run has ended: no run left, so no cancel button either.
    assert not [b for b in at.button if b.key == "backtesting_cancel_btn"]
    assert "_backtesting_active_run" not in at.session_state


def test_result_of_a_failed_run_survives_the_next_rerun():
    at = _active_run(1, cancel_requested=False)
    at.run()
    assert not at.exception
    assert any("Exit-Code 1" in err.value for err in at.error)


def test_generate_button_is_locked_while_a_run_of_the_session_is_going():
    at = AppTest.from_file(str(_ACTIVE_RUN_SCRIPT), default_timeout=30)
    at.session_state["_fake_run_cfg"] = {"exit_code": 0, "cancel_requested": False, "running": True}
    at.run()
    assert not at.exception
    generate = [b for b in at.button if b.key == "backtesting_cons_data_generate_btn"]
    assert generate and generate[0].disabled


def test_failed_run_is_not_reported_as_cancelled():
    at = _active_run(130, cancel_requested=False)
    assert not at.exception
    assert not any("abgebrochen" in info.value for info in at.info)
    assert any("Exit-Code 130" in err.value for err in at.error)


_CAPTURE_SCRIPT = Path(__file__).parent / "scripts" / "run_backtesting_start_capture.py"
_BOXES = ("backtesting_reference_historical", "backtesting_reference_l0", "backtesting_reference_l1")


def _boxes(at: AppTest) -> dict:
    return {box.key: box for box in at.checkbox if box.key in _BOXES}


def test_reference_boxes_default_to_historical_and_referenz_ohne_speicher(monkeypatch):
    monkeypatch.setenv("EARNIE_UI_MODES", "scenario_explorer")
    at = AppTest.from_file(str(_CAPTURE_SCRIPT), default_timeout=30).run()
    assert not at.exception
    boxes = _boxes(at)
    assert {key: box.value for key, box in boxes.items()} == {
        "backtesting_reference_historical": True,
        "backtesting_reference_l0": True,
        "backtesting_reference_l1": False,
    }
    assert [boxes[key].label for key in _BOXES] == [
        "Historisch",
        "Referenz ohne Speicher",
        "Wechselrichter-Eigenverbrauch (L1)",
    ]
    assert not any(box.disabled for box in boxes.values())


def test_rule_reference_locks_l0_and_l1_on(monkeypatch):
    monkeypatch.setenv("EARNIE_UI_MODES", "scenario_explorer,rule_reference")
    at = AppTest.from_file(str(_CAPTURE_SCRIPT), default_timeout=30).run()
    boxes = _boxes(at)
    assert boxes["backtesting_reference_l0"].value and boxes["backtesting_reference_l0"].disabled
    assert boxes["backtesting_reference_l1"].value and boxes["backtesting_reference_l1"].disabled
    assert not boxes["backtesting_reference_historical"].disabled


def test_run_button_passes_the_ticked_boxes(monkeypatch):
    monkeypatch.setenv("EARNIE_UI_MODES", "scenario_explorer")
    at = AppTest.from_file(str(_CAPTURE_SCRIPT), default_timeout=30).run()
    at.checkbox(key="backtesting_reference_historical").uncheck()
    at.checkbox(key="backtesting_reference_l1").check().run()
    run_button = at.button(key="backtesting_run_btn")
    if run_button.disabled:
        import pytest

        pytest.skip("Fixture ohne cons_data: Startknopf deaktiviert")
    run_button.click().run()
    assert not at.exception
    assert at.session_state["_captured_start"]["references"] == ("l0", "l1")
