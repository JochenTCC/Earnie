"""AppTest-Smoketest für Preis-Prognose (Dev) (echtes Rendering, headless).

Rendert gegen die vorhandenen Trainings-Datasets unter data/cache/ (lokale
CSV/JSON, kein Netzwerkzugriff) und passt Modell + Holdout-Auswertung an.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_price_forecast.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_present():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "💹 Preis-Prognose (Dev)"
