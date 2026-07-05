"""Tests für main.py-Sync-UI-Texte."""
from __future__ import annotations

from ui.main_py_sync import main_py_sync_status_message, sync_footer_caption


def test_status_message_shows_retry_not_full_fallback():
    text = main_py_sync_status_message(15, 30, "wait_main")
    assert "spätestens in 15 s" in text
    assert "Fallback mit Altplan nach **30 s**" in text
    assert "noch ca." not in text


def test_sync_footer_waiting():
    assert "Abgleich spätestens in `12` s" in sync_footer_caption(12, 25)
    assert "Fallback nach `25` s" in sync_footer_caption(12, 25)


def test_sync_footer_ready():
    assert sync_footer_caption(0, 0) == " · **App-Sync** bereit"
