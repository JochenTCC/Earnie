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


def test_earnie_points_section_present():
    """Read-only Earnie-Points block: shows a number or the reason it cannot be computed."""
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception
    assert "Earnie-Points dieser Anlage" in [h.value for h in at.subheader]
    metric_labels = {m.label for m in at.metric}
    warnings = [w.value for w in at.warning]
    assert "Earnie-Points gesamt" in metric_labels or any(
        w.startswith("Earnie-Points nicht berechenbar") for w in warnings
    )


def _points_view_app():
    from ui import earnie_points_view

    earnie_points_view.render_earnie_points()


def test_earnie_points_view_shows_total_and_breakdown(monkeypatch):
    from ui import earnie_points_view

    monkeypatch.setattr(
        earnie_points_view,
        "compute_live_points",
        lambda: {"total": 7, "pv": 2, "storage": 2, "wallbox": 2, "heat": 1, "other": 0},
    )
    at = AppTest.from_function(_points_view_app).run()
    assert not at.exception
    assert at.metric[0].label == "Earnie-Points gesamt"
    assert at.metric[0].value == "7"
    assert len(at.table) == 1
    assert not at.warning


def test_earnie_points_view_shows_error_instead_of_number(monkeypatch):
    from ui import earnie_points_view

    def _boom():
        raise ValueError("Live-Szenario hat kein house_profile_id.")

    monkeypatch.setattr(earnie_points_view, "compute_live_points", _boom)
    at = AppTest.from_function(_points_view_app).run()
    assert not at.exception
    assert not at.metric
    assert "kein house_profile_id" in at.warning[0].value
