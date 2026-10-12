"""Shadow R3 transport intercept helpers."""
from __future__ import annotations

import pytest

from runtime_store.shadow.transport import ext_get, hub_get, safe_record


def test_hub_get_shadow_uses_replay_only(monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    calls: list[str] = []

    def replay() -> str:
        calls.append("replay")
        return "from-feed"

    def live() -> str:
        calls.append("live")
        return "from-network"

    assert hub_get(replay=replay, live=live) == "from-feed"
    assert calls == ["replay"]


def test_hub_get_prod_uses_live_only(monkeypatch):
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    calls: list[str] = []

    assert hub_get(
        replay=lambda: (calls.append("replay") or "feed"),
        live=lambda: (calls.append("live") or "net"),
    ) == "net"
    assert calls == ["live"]


def test_ext_get_shadow_fallback_unrecorded(monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    calls: list[str] = []

    def replay():
        calls.append("replay")
        return None

    def live():
        calls.append("live")
        return {"ok": True}

    assert ext_get(replay=replay, live=live, allow_live_fallback=True) == {"ok": True}
    assert calls == ["replay", "live"]


def test_ext_get_shadow_no_fallback(monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    calls: list[str] = []

    assert (
        ext_get(
            replay=lambda: (calls.append("replay") or None),
            live=lambda: (calls.append("live") or "net"),
            allow_live_fallback=False,
        )
        is None
    )
    assert calls == ["replay"]


def test_ext_get_shadow_hit_skips_live(monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    calls: list[str] = []

    assert (
        ext_get(
            replay=lambda: (calls.append("replay") or {"from": "feed"}),
            live=lambda: (calls.append("live") or {"from": "net"}),
            allow_live_fallback=True,
        )
        == {"from": "feed"}
    )
    assert calls == ["replay"]


def test_safe_record_never_raises(monkeypatch):
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)

    def boom(*_a, **_k):
        raise RuntimeError("recorder blew up")

    monkeypatch.setattr(
        "runtime_store.shadow.transport.record_transport", boom
    )
    safe_record("ext:test", ok=False, error="x")  # must not raise
