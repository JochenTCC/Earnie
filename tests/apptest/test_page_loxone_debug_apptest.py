"""AppTest-Smoketest für EHAL-Com / Loxone-Debug (echtes Rendering, headless).

Die Live-Lesen-Sektion läuft als autouse-Fragment und würde bei gesetzten
LOXONE_IP/USER/PASS echte Miniserver-Reads auslösen (aus einer lokalen
.env geladen, unabhängig von der Fixture-Config) — deshalb werden die
Zugangsdaten hier explizit entfernt, damit der Test offline und ohne
Netzwerkzugriff bleibt (Hinweistext "Zugangsdaten fehlen" statt Live-Read).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_loxone_debug.py"


@pytest.fixture(autouse=True)
def _no_loxone_credentials(monkeypatch):
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.delenv("LOXONE_USER", raising=False)
    monkeypatch.delenv("LOXONE_PASS", raising=False)


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_and_missing_credentials_notice():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "🔗 EHAL-Com"
    assert any(
        "Zugangsdaten fehlen" in caption.value for caption in at.caption
    )
