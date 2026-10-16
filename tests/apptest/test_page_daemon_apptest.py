"""AppTest-Smoketest für Optimierer-Dienst / Daemon Control (echtes Rendering, headless).

Zeigt nur den Status (kein main.py-Lock in der isolierten Fixture-Umgebung
vorhanden) und die Start/Stop/Neustart-Buttons — keine Buttons werden
geklickt, um keinen echten Subprozess zu starten.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_daemon.py"


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_title_and_status_present():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert at.title[0].value == "🛠️ Optimierer-Dienst"
    labels = {b.label for b in at.button}
    assert {"Start", "Stop", "Neustart", "Gehe nach Oben"} <= labels


def test_usage_ping_settings_section_present():
    """P3: Nutzungsstatistik toggle + payload expander on Optimierer-Dienst."""
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception
    subheaders = [h.value for h in at.subheader]
    assert "Nutzungsstatistik" in subheaders
    toggle_labels = {t.label for t in at.toggle}
    assert "Anonyme Nutzungsstatistik senden" in toggle_labels
    expander_labels = {e.label for e in at.expander}
    assert "Was wird gesendet?" in expander_labels
