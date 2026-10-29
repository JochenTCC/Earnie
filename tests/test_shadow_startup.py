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


def _write_meta(
    feed: Path,
    *,
    prod_runtime: str,
    data_model: int | None = None,
    ehal_backend: str = "ha",
    loxone_feed: str | None = None,
) -> None:
    from runtime_store.data_model import CURRENT_DATA_MODEL

    if data_model is None:
        data_model = CURRENT_DATA_MODEL
    feed.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    meta: dict = {
        "feed_schema": FEED_SCHEMA,
        "earnie_version": "2.6.0-test",
        "earnie_data_model": data_model,
        "ehal_backend": ehal_backend,
        "prod_runtime_dir": prod_runtime,
        "heartbeat_ts": ts,
        "cycle_seq": 1,
    }
    if loxone_feed is not None:
        meta["loxone_feed"] = loxone_feed
    (feed / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
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


def test_startup_refuses_incompatible_data_model_with_shared_config(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    shadow_rt = tmp_path / "shadow_rt"
    config = tmp_path / "prod_config"
    feed = config / "shadow_feed"  # feed under the config → shared Prod config
    _write_meta(feed, prod_runtime=str(tmp_path / "prod_rt"), data_model=99)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(shadow_rt))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    with pytest.raises(ShadowStartupError, match="earnie_data_model"):
        ensure_shadow_startup()


def test_startup_private_config_ignores_prod_data_model(monkeypatch, tmp_path):
    """Prod on an older data model, Shadow on its own migrated config (NAS dev + prod)."""
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    shadow_rt = tmp_path / "shadow_rt"
    config = tmp_path / "shadow_config"
    config.mkdir()
    feed = tmp_path / "prod_feed"  # outside the Shadow config → private config
    _write_meta(feed, prod_runtime=str(tmp_path / "prod_rt"), data_model=99)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(shadow_rt))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    meta = ensure_shadow_startup()
    assert meta["earnie_data_model"] == 99
    assert (shadow_rt / ".shadow_runtime").is_file()


def test_startup_private_config_still_checks_feed_schema(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    config = tmp_path / "shadow_config"
    config.mkdir()
    feed = tmp_path / "prod_feed"
    _write_meta(feed, prod_runtime=str(tmp_path / "prod_rt"))
    meta = json.loads((feed / "meta.json").read_text(encoding="utf-8"))
    meta["feed_schema"] = FEED_SCHEMA + 1
    (feed / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "shadow_rt"))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    with pytest.raises(ShadowStartupError, match="feed_schema"):
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


def test_startup_clears_stale_loxone_auth_error(monkeypatch, tmp_path):
    """Shadow must drop leftover auth gates from prior non-Shadow runs."""
    from runtime_store.loxone_auth_error import (
        AUTH_ERROR_FILENAME,
        load_loxone_auth_error,
        persist_loxone_auth_error,
    )

    monkeypatch.setenv("EARNIE_SHADOW", "1")
    shadow_rt = tmp_path / "shadow_rt"
    shadow_rt.mkdir()
    feed = tmp_path / "feed"
    _write_meta(feed, prod_runtime=str(tmp_path / "prod_rt"))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(shadow_rt))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    persist_loxone_auth_error(
        message="Loxone auth failed (HTTP 401)",
        http_status=401,
        source="startup_checks",
    )
    assert load_loxone_auth_error() is not None
    ensure_shadow_startup()
    assert load_loxone_auth_error() is None
    assert not (shadow_rt / AUTH_ERROR_FILENAME).is_file()


def test_startup_refuses_loxone_without_feed_capability(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    shadow_rt = tmp_path / "shadow_rt"
    feed = tmp_path / "feed"
    _write_meta(
        feed,
        prod_runtime=str(tmp_path / "prod_rt"),
        ehal_backend="loxone",
    )
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(shadow_rt))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    with pytest.raises(ShadowStartupError, match="loxone_feed"):
        ensure_shadow_startup()


def test_startup_ok_loxone_with_feed_capability(monkeypatch, tmp_path):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    shadow_rt = tmp_path / "shadow_rt"
    feed = tmp_path / "feed"
    _write_meta(
        feed,
        prod_runtime=str(tmp_path / "prod_rt"),
        ehal_backend="loxone",
        loxone_feed="push",
    )
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(shadow_rt))
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    meta = ensure_shadow_startup()
    assert meta["loxone_feed"] == "push"


def test_startup_noop_without_shadow(monkeypatch):
    assert ensure_shadow_startup() == {}
