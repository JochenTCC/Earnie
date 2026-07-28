# tests/test_setup_progress.py
"""Tests für Greenfield-Sidebar-Hinweise (ohne Loxone-Zugangs-Expander)."""
from __future__ import annotations

from ui import setup_progress


class _FakeSidebar:
    def __init__(self):
        self.calls: list[tuple[str, bool]] = []
        self.info_calls: list[str] = []
        self.success_calls: list[str] = []

    def expander(self, label: str, *, expanded: bool = False):
        self.calls.append((label, expanded))
        raise AssertionError("Loxone sidebar expander must not be used")

    def info(self, msg: str) -> None:
        self.info_calls.append(msg)

    def success(self, msg: str) -> None:
        self.success_calls.append(msg)


def test_render_setup_progress_notice_points_to_ehal_com_when_planning_ready(
    monkeypatch,
):
    sidebar = _FakeSidebar()
    monkeypatch.setattr(setup_progress.st, "sidebar", sidebar)
    monkeypatch.setattr(setup_progress, "needs_planning_onboarding", lambda: True)
    monkeypatch.setattr(setup_progress, "is_planning_ready", lambda: True)
    monkeypatch.setattr(setup_progress, "is_betrieb_unlocked", lambda: False)

    setup_progress.render_setup_progress_notice()

    assert sidebar.calls == []
    assert any("EHAL-Com" in msg for msg in sidebar.success_calls)


def test_render_setup_progress_notice_skips_when_onboarding_done(monkeypatch):
    sidebar = _FakeSidebar()
    monkeypatch.setattr(setup_progress.st, "sidebar", sidebar)
    monkeypatch.setattr(setup_progress, "needs_planning_onboarding", lambda: False)

    setup_progress.render_setup_progress_notice()

    assert sidebar.calls == []
    assert sidebar.info_calls == []
    assert sidebar.success_calls == []
