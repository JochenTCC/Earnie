"""auto_persist must not crash when Shadow Mode blocks config writes."""
from __future__ import annotations

import ui.auto_persist as ap


def test_auto_persist_skips_in_shadow(monkeypatch):
    calls: list[int] = []
    session: dict = {}
    captions: list[str] = []

    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setattr(ap.st, "session_state", session)
    monkeypatch.setattr(ap.st, "caption", lambda msg: captions.append(msg))

    wrote = ap.auto_persist(
        state_key="plant_export",
        payload={"enabled": True, "max_kw": 5.0},
        save=lambda: calls.append(1),
    )
    assert wrote is False
    assert calls == []
    assert any("schreibgeschützt" in c for c in captions)

    wrote2 = ap.auto_persist(
        state_key="plant_export",
        payload={"enabled": True, "max_kw": 5.0},
        save=lambda: calls.append(1),
    )
    assert wrote2 is False
    assert calls == []


def test_auto_persist_writes_when_not_shadow(monkeypatch):
    calls: list[int] = []
    session: dict = {}
    captions: list[str] = []

    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.setattr(ap.st, "session_state", session)
    monkeypatch.setattr(ap.st, "caption", lambda msg: captions.append(msg))

    wrote = ap.auto_persist(
        state_key="plant_export",
        payload={"enabled": True, "max_kw": 5.0},
        save=lambda: calls.append(1),
    )
    assert wrote is True
    assert calls == [1]
    assert captions == ["Gespeichert"]
