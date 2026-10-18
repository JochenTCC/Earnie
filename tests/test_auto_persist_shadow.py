"""auto_persist must not crash when Shadow Mode blocks config writes."""
from __future__ import annotations

import ui.auto_persist as ap


def test_auto_persist_skips_in_shadow(monkeypatch, tmp_path):
    calls: list[int] = []
    session: dict = {}
    captions: list[str] = []

    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg))
    monkeypatch.delenv("EARNIE_SHADOW_FEED_PATH", raising=False)
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


def test_auto_persist_writes_with_private_shadow_config(monkeypatch, tmp_path):
    calls: list[int] = []
    session: dict = {}
    captions: list[str] = []

    cfg = tmp_path / "local_config"
    cfg.mkdir()
    feed = tmp_path / "prod_feed"
    feed.mkdir()
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "rt"))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
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
    assert session.get("_auto_persist_flash::plant_export") == "Gespeichert"


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
    assert session.get("_auto_persist_flash::plant_export") == "Gespeichert"


def test_auto_persist_flash_survives_simulated_rerun(monkeypatch):
    """Callers that ``st.rerun()`` after write still show Gespeichert once."""
    calls: list[int] = []
    session: dict = {}
    captions: list[str] = []

    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.setattr(ap.st, "session_state", session)
    monkeypatch.setattr(ap.st, "caption", lambda msg: captions.append(msg))

    assert (
        ap.auto_persist(
            state_key="battery",
            payload={"id": "b1", "kwh": 5},
            save=lambda: calls.append(1),
        )
        is True
    )
    # Simulate rerun: fingerprint matches, but flash must still caption once.
    captions.clear()
    assert (
        ap.auto_persist(
            state_key="battery",
            payload={"id": "b1", "kwh": 5},
            save=lambda: calls.append(1),
        )
        is False
    )
    assert calls == [1]
    assert captions == ["Gespeichert"]
    assert "_auto_persist_flash::battery" not in session
