"""AppTest-Smoketest für Preis-Prognose (Dev) (echtes Rendering, headless).

Rendert gegen die vorhandenen Trainings-Datasets unter data/cache/ (lokale
CSV/JSON, kein Netzwerkzugriff) und passt Modell + Holdout-Auswertung an.

default_timeout=30 statt der AppTest-Vorgabe (3s): Modell-Fit und Holdout-Auswertung
liegen unter voller Test-Suite-Last (xdist) knapp über 3s und timeouten sonst spuriös.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_price_forecast.py"
_TIMEOUT_S = 30


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT_S).run()
    assert not at.exception


def test_title_present():
    at = AppTest.from_file(str(_SCRIPT), default_timeout=_TIMEOUT_S).run()
    assert at.title[0].value == "💹 Preis-Prognose (Dev)"
