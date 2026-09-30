"""Shadow Mode startup checks (§4.2)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from runtime_store.shadow import feed as shadow_feed
from runtime_store.shadow.errors import ShadowStartupError
from runtime_store.shadow.feed import FEED_SCHEMA
from runtime_store.shadow.startup import (
    ensure_shadow_runtime_marker,
    ensure_shadow_startup,
    has_explicit_runtime_dir,
)


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.delenv("EARNIE_SHADOW_FEED_PATH", raising=False)
    monkeypatch.delenv("EARNIE_RUNTIME_PATH", raising=False)
    monkeypatch.delenv("EARNIE_ENV_PATH", raising=False)
    shadow_feed.reset_for_tests()
    yield
    shadow_feed.reset_for_tests()


def _write_meta(feed: Path, *, prod_runtime: str, data_model: int = 3) -> None:
    feed.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    (feed / "meta.json").write_text(
        json.dumps(
            {
                "feed_schema": FEED_SCHEMA,
                "earnie_version": "2.6.0-test",
                "earnie_data_model": data_model,
                "ehal_backend": "ha",
                "prod_runtime_dir": prod_runtime,
                "heartbeat_ts": ts,
                "cycle_seq": 1,
            }
        ),
        encoding="utf-8",
    )
    (feed / "latest.json").write_text(
        json.dumps({"cycle_seq": 1, "cycle_ts": ts, "records": {}}),
        encoding="utf-8",
    )


def test_has_explicit_runtime_requires_env(monkeypatch):
    assert has_explicit_runtime_dir() is False
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", "C:/shadow-rt")
    assert has_explicit_runtime_dir() is True


def test_startup_refuses_without_runtime_env(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    feed = tmp_path / "feed"
    _write_meta(feed, prod_runtime=str(tmp_path / "prod_rt"))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    with pytest.raises(ShadowStartupError, match="EARNIE_RUNTIME_PATH"):
        ensure_shadow_startup()


def test_startup_refuses_missing_meta(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "shadow_rt"))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(tmp_path / "missing_feed"))
    with pytest.raises(ShadowStartupError, match="fehlt"):
        ensure_shadow_startup()


def test_startup_refuses_incompatible_data_model(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    shadow_rt = tmp_path / "shadow_rt"
    feed = tmp_path / "feed"
    _write_meta(feed, prod_runtime=str(tmp_path / "prod_rt"), data_model=99)
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(shadow_rt))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    with pytest.raises(ShadowStartupError, match="earnie_data_model"):
        ensure_shadow_startup()


def test_startup_refuses_same_runtime_as_prod(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    shared = tmp_path / "shared_rt"
    shared.mkdir()
    feed = tmp_path / "feed"
    _write_meta(feed, prod_runtime=str(shared.resolve()))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(shared))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    with pytest.raises(ShadowStartupError, match="Prod-Runtime"):
        ensure_shadow_startup()


def test_startup_ok_writes_marker(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    shadow_rt = tmp_path / "shadow_rt"
    feed = tmp_path / "feed"
    _write_meta(feed, prod_runtime=str(tmp_path / "prod_rt"))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(shadow_rt))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    meta = ensure_shadow_startup()
    assert meta["feed_schema"] == FEED_SCHEMA
    assert (shadow_rt / ".shadow_runtime").is_file()
    ensure_shadow_runtime_marker()  # idempotent


def test_startup_noop_without_shadow(monkeypatch):
    assert ensure_shadow_startup() == {}
