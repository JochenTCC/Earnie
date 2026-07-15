"""Tests für Live-Modus-Snapshot-Cache (S-2-Navigation)."""
from __future__ import annotations

from ui.live_mode import _snapshot_cache_key


def test_snapshot_cache_key_includes_s2_navigation():
    snapshot = {"completed_at": "2026-07-15T08:00:00+02:00"}
    base = _snapshot_cache_key("2026-07-15T10:00", snapshot, 0, 0)
    forecast = _snapshot_cache_key("2026-07-15T10:00", snapshot, 0, 1)
    past = _snapshot_cache_key("2026-07-15T10:00", snapshot, 1, 0)
    assert base != forecast
    assert base != past
    assert forecast != past
