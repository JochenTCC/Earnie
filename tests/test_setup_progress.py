# tests/test_setup_progress.py
"""Tests für Greenfield-Sidebar (Loxone-Zugang unabhängig von Planungs-Hinweisen)."""
from __future__ import annotations

from ui import setup_progress


class _FakeSidebarExpander:
    def __init__(self, calls: list[tuple[str, bool]]):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def caption(self, _text: str) -> None:
        return None


class _FakeSidebar:
    def __init__(self):
        self.calls: list[tuple[str, bool]] = []

    def expander(self, label: str, *, expanded: bool = False):
        self.calls.append((label, expanded))
        return _FakeSidebarExpander(self.calls)


def test_render_deferred_loxone_sidebar_skips_when_not_deferred(monkeypatch):
    sidebar = _FakeSidebar()
    monkeypatch.setattr(setup_progress.st, "sidebar", sidebar)
    monkeypatch.setattr(setup_progress, "should_show_loxone_sidebar", lambda: False)

    setup_progress.render_deferred_loxone_sidebar()

    assert sidebar.calls == []


def test_render_deferred_loxone_sidebar_renders_expander_when_deferred(monkeypatch):
    sidebar = _FakeSidebar()
    monkeypatch.setattr(setup_progress.st, "sidebar", sidebar)
    monkeypatch.setattr(setup_progress, "should_show_loxone_sidebar", lambda: True)
    monkeypatch.setattr(setup_progress, "loxone_credentials_configured", lambda: False)
    monkeypatch.setattr(
        setup_progress,
        "render_loxone_credentials_form",
        lambda **kwargs: None,
    )

    setup_progress.render_deferred_loxone_sidebar()

    assert sidebar.calls == [("Loxone-Zugang (Live / Silent-Modus)", True)]


def test_render_deferred_loxone_sidebar_shows_hint_when_credentials_ready(monkeypatch):
    sidebar = _FakeSidebar()
    caption_calls: list[str] = []
    monkeypatch.setattr(setup_progress.st, "sidebar", sidebar)
    monkeypatch.setattr(setup_progress, "should_show_loxone_sidebar", lambda: True)
    monkeypatch.setattr(setup_progress, "loxone_credentials_configured", lambda: True)
    monkeypatch.setattr(setup_progress.st, "success", lambda _msg: None)
    monkeypatch.setattr(setup_progress.st, "caption", lambda msg: caption_calls.append(msg))

    setup_progress.render_deferred_loxone_sidebar()

    assert sidebar.calls == [("Loxone-Zugang (Live / Silent-Modus)", False)]
    assert any("Loxone-Kommunikation" in msg for msg in caption_calls)


def test_render_setup_progress_notice_does_not_gate_loxone_sidebar(monkeypatch):
    """Planungs-Hinweise dürfen den Loxone-Expander nicht mehr umschließen."""
    sidebar = _FakeSidebar()
    monkeypatch.setattr(setup_progress.st, "sidebar", sidebar)
    monkeypatch.setattr(setup_progress, "needs_planning_onboarding", lambda: False)

    setup_progress.render_setup_progress_notice()

    assert sidebar.calls == []
