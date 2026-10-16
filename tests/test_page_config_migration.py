"""Unit tests for ConfigMigration P3 wizard helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runtime_store.main_daemon import DaemonStatus
from ui.pages import page_config_migration as page
from ui.truth_banner import OFFICIAL_REPO_URL


def test_release_notes_url_uses_official_repo_and_version():
    url = page.release_notes_url("2.7.0-alpha.1")
    assert url == f"{OFFICIAL_REPO_URL}/releases/tag/v2.7.0-alpha.1"


def test_resolve_export_bytes_fails_loud_on_unknown_kind():
    with pytest.raises(ValueError, match="Unbekannter export_kind"):
        page.resolve_export_bytes("loxone_zip")


def test_continue_after_migration_skips_start_when_auto_start_off(monkeypatch):
    monkeypatch.delenv("EARNIE_AUTO_START_MAIN", raising=False)
    start = MagicMock()
    monkeypatch.setattr("runtime_store.main_daemon.start", start)
    monkeypatch.setattr(
        "runtime_store.main_daemon.status",
        lambda: DaemonStatus(state="stopped", pid=None, lock_path="/tmp/x"),
    )
    page.continue_after_migration()
    start.assert_not_called()


def test_continue_after_migration_starts_when_auto_start_on(monkeypatch):
    monkeypatch.setenv("EARNIE_AUTO_START_MAIN", "1")
    started = DaemonStatus(state="running", pid=42, lock_path="/tmp/x")
    start = MagicMock(return_value=started)
    monkeypatch.setattr("runtime_store.main_daemon.start", start)
    monkeypatch.setattr(
        "runtime_store.main_daemon.status",
        lambda: DaemonStatus(state="stopped", pid=None, lock_path="/tmp/x"),
    )
    monkeypatch.setattr(
        "integrations.ha_supervisor.is_homeassistant_addon_context",
        lambda: False,
    )
    page.continue_after_migration()
    start.assert_called_once()
