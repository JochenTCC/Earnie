"""Shadow Mode transport replay (§6.1)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from integrations.ha_adapter import HaAdapter, HaConfig, HaHttpError
from integrations.loxone_client import _fetch_loxone_io_all, fetch_loxone_raw_value
from runtime_store.shadow import feed as shadow_feed
from runtime_store.shadow import reader as shadow_reader
from runtime_store.shadow import replay as shadow_replay
from runtime_store.shadow.errors import ShadowBackendAccessError
from runtime_store.shadow.replay import assert_not_shadow_backend


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.delenv("EARNIE_SHADOW_FEED_PATH", raising=False)
    shadow_feed.reset_for_tests()
    shadow_reader.reset_reader_for_tests()
    shadow_replay.reset_replay_for_tests()
    yield
    shadow_feed.reset_for_tests()
    shadow_reader.reset_reader_for_tests()
    shadow_replay.reset_replay_for_tests()


def _utc(offset_sec: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=offset_sec)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_feed(
    feed: Path,
    records: dict,
    *,
    heartbeat_offset: int = 0,
    cycle_offset: int | None = None,
) -> None:
    feed.mkdir(parents=True, exist_ok=True)
    hb = _utc(heartbeat_offset)
    cycle_ts = _utc(heartbeat_offset if cycle_offset is None else cycle_offset)
    (feed / "meta.json").write_text(
        json.dumps(
            {
                "feed_schema": 1,
                "earnie_version": "2.6.0",
                "earnie_data_model": 4,
                "ehal_backend": "ha",
                "prod_runtime_dir": "/prod",
                "heartbeat_ts": hb,
                "cycle_seq": 1,
            }
        ),
        encoding="utf-8",
    )
    (feed / "latest.json").write_text(
        json.dumps({"cycle_seq": 1, "cycle_ts": cycle_ts, "records": records}),
        encoding="utf-8",
    )


def test_replay_loxone_io(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    _write_feed(
        feed,
        {
            "loxone:io:Soc": {
                "key": "loxone:io:Soc",
                "ts": _utc(),
                "ok": True,
                "status": 200,
                "payload": {"LL": {"value": "55.5"}},
                "error": None,
            }
        },
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    assert fetch_loxone_raw_value("Soc") == "55.5"


def test_replay_loxone_io_all(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    ll = {"SpecialState10": {"value": "1"}, "Code": "200"}
    _write_feed(
        feed,
        {
            "loxone:io_all:Clock": {
                "key": "loxone:io_all:Clock",
                "ts": _utc(),
                "ok": True,
                "status": 200,
                "payload": ll,
                "error": None,
            }
        },
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    assert _fetch_loxone_io_all("Clock") == ll


def test_replay_missing_loxone_returns_none(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    _write_feed(feed, {})
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    assert fetch_loxone_raw_value("Missing") is None


def test_replay_stale_treated_as_missing(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    old = _utc(-300)
    _write_feed(
        feed,
        {
            "loxone:io:Soc": {
                "key": "loxone:io:Soc",
                "ts": old,
                "ok": True,
                "status": 200,
                "payload": {"LL": {"value": "10"}},
                "error": None,
            }
        },
        heartbeat_offset=0,
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("EARNIE_SHADOW_MAX_AGE_SEC", "60")
    assert fetch_loxone_raw_value("Soc") is None


def test_replay_keeps_cycle_fresh_when_heartbeat_advances(monkeypatch, tmp_path):
    """Sampler heartbeat flush must not stale IO recorded at cycle_ts."""
    feed = tmp_path / "feed"
    cycle = _utc(-150)
    _write_feed(
        feed,
        {
            "loxone:io:Earnie_Pool_Temp_Ist": {
                "key": "loxone:io:Earnie_Pool_Temp_Ist",
                "ts": cycle,
                "ok": True,
                "status": 200,
                "payload": {"LL": {"value": "37.5"}},
                "error": None,
            }
        },
        heartbeat_offset=0,
        cycle_offset=-150,
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("EARNIE_SHADOW_MAX_AGE_SEC", "120")
    assert fetch_loxone_raw_value("Earnie_Pool_Temp_Ist") == "37.5"


def test_replay_sampler_newer_than_cycle_stays_fresh(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    _write_feed(
        feed,
        {
            "loxone:io:Soc": {
                "key": "loxone:io:Soc",
                "ts": _utc(-30),
                "ok": True,
                "status": 200,
                "payload": {"LL": {"value": "55"}},
                "error": None,
            }
        },
        heartbeat_offset=0,
        cycle_offset=-200,
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("EARNIE_SHADOW_MAX_AGE_SEC", "120")
    assert fetch_loxone_raw_value("Soc") == "55"


def test_replay_ha_get(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    path = "/api/states/sensor.soc"
    payload = {"entity_id": "sensor.soc", "state": "42", "attributes": {}}
    _write_feed(
        feed,
        {
            f"ha:get:{path}": {
                "key": f"ha:get:{path}",
                "ts": _utc(),
                "ok": True,
                "status": 200,
                "payload": payload,
                "error": None,
            }
        },
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    adapter = HaAdapter(
        HaConfig(base_url="http://unused", token="x", adapter_id="t", entities={})
    )
    assert adapter._get_json(path) == payload


def test_replay_ha_missing_raises(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    _write_feed(feed, {})
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    adapter = HaAdapter(
        HaConfig(base_url="http://unused", token="x", adapter_id="t", entities={})
    )
    with pytest.raises(HaHttpError):
        adapter._get_json("/api/states/sensor.x")


def test_assert_backend_blocked_in_shadow(monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    with pytest.raises(ShadowBackendAccessError):
        assert_not_shadow_backend("probe")


def test_requests_not_called_for_loxone_replay(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    _write_feed(
        feed,
        {
            "loxone:io:X": {
                "key": "loxone:io:X",
                "ts": _utc(),
                "ok": True,
                "status": 200,
                "payload": {"LL": {"value": "1"}},
                "error": None,
            }
        },
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    get = MagicMock(side_effect=AssertionError("network"))
    monkeypatch.setattr("integrations.loxone_client.requests.get", get)
    assert fetch_loxone_raw_value("X") == "1"
    get.assert_not_called()
