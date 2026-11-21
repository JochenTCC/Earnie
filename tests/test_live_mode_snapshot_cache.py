"""Tests für Live-Modus-Snapshot-Cache (S-2-Navigation)."""
from __future__ import annotations

from ui.live_mode import _snapshot_cache_key


def test_snapshot_cache_key_includes_s2_navigation():
    snapshot = {"completed_at": "2026-07-15T08:00:00+02:00"}
    base = _snapshot_cache_key("2026-07-15T10:00", snapshot, 0, 0, "segment")
    forecast = _snapshot_cache_key("2026-07-15T10:00", snapshot, 0, 1, "segment")
    past = _snapshot_cache_key("2026-07-15T10:00", snapshot, 1, 0, "segment")
    full = _snapshot_cache_key("2026-07-15T10:00", snapshot, 0, 0, "full")
    assert base != forecast
    assert base != past
    assert forecast != past
    assert base != full


def test_snapshot_cache_key_changes_when_the_ledger_books_a_slot(monkeypatch):
    """main.py writes the snapshot before booking the ledger slot; the key must follow the ledger."""
    from datetime import datetime
    from types import SimpleNamespace

    from ui import live_mode

    booked = {"last": None}

    def _peek():
        last = booked["last"]
        state = SimpleNamespace(last_slot_start=last) if last is not None else None
        return SimpleNamespace(state=state, restart_reason=None)

    monkeypatch.setattr(live_mode.savings_ledger_store, "peek_state", _peek)
    snapshot = {"completed_at": "2026-07-15T08:00:00+02:00"}
    before = _snapshot_cache_key("2026-07-15T10:00", snapshot, 0, 0, "segment")
    booked["last"] = datetime.fromisoformat("2026-07-15T09:45:00+02:00")
    after = _snapshot_cache_key("2026-07-15T10:00", snapshot, 0, 0, "segment")
    assert before != after
