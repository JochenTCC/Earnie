"""Shadow Mode transport replay (§6.1)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from integrations.ha_adapter import HaAdapter, HaConfig, HaHttpError
from runtime_store.shadow import feed as shadow_feed
from runtime_store.shadow import reader as shadow_reader
from runtime_store.shadow import replay as shadow_replay
from runtime_store.shadow.errors import ShadowBackendAccessError
from runtime_store.shadow.replay import assert_not_shadow_backend, replay_loxone_io


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
    assert replay_loxone_io("loxone:io:Soc") == "55.5"


def test_replay_missing_loxone_returns_none(monkeypatch, tmp_path):
    feed = tmp_path / "feed"
    _write_feed(feed, {})
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    assert replay_loxone_io("loxone:io:Missing") is None


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
    assert replay_loxone_io("loxone:io:Soc") is None


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
    assert replay_loxone_io("loxone:io:Earnie_Pool_Temp_Ist") == "37.5"


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
    assert replay_loxone_io("loxone:io:Soc") == "55"


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


def test_probe_entries_raise_in_shadow(monkeypatch):
    """R3: MCP / greenfield / EHAL mapping probes must hard-forbid, not UI-only."""
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    from integrations.ha_adapter import HaAdapter, HaConfig
    from integrations.loxone_connectivity import probe_loxone_http_access
    from integrations.loxone_greenfield_import import run_greenfield_import
    # Import structure before mcp_probe to avoid circular import init order.
    from integrations.loxone_structure import scan_structure
    from integrations.loxone_mcp_probe import probe_mcp17

    with pytest.raises(ShadowBackendAccessError):
        probe_mcp17("https://example.invalid/mcp")
    with pytest.raises(ShadowBackendAccessError):
        probe_loxone_http_access(host="10.0.0.1", username="u", password="p")
    with pytest.raises(ShadowBackendAccessError):
        run_greenfield_import({"controls": {}})
    with pytest.raises(ShadowBackendAccessError):
        HaAdapter(
            HaConfig(base_url="http://unused", token="x", adapter_id="t", entities={})
        ).list_mappable_entities()
    with pytest.raises(ShadowBackendAccessError):
        scan_structure(host="10.0.0.1", username="u", password="p")


def test_replay_loxone_io_reads_feed_without_network(monkeypatch, tmp_path):
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
    assert replay_loxone_io("loxone:io:X") == "1"


def test_shadow_read_push_value_uses_feed_soc(monkeypatch, tmp_path) -> None:
    """Shadow has no VO listener; SoC must come from ``loxone:io:<ehal_id>``."""
    from runtime_store import loxone_push_inbox as inbox

    eid = "ess.15_kwh_speicher.sens_ess_soc"
    feed = tmp_path / "feed"
    _write_feed(
        feed,
        {
            f"loxone:io:{eid}": {
                "key": f"loxone:io:{eid}",
                "ts": _utc(),
                "ok": True,
                "status": None,
                "payload": {"LL": {"value": "61.5"}},
                "error": None,
            }
        },
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    inbox.reset_memory_for_tests()
    value, state = inbox.read_push_value(eid)
    assert (value, state) == (61.5, inbox.STATE_OK)


def test_shadow_soc_older_than_vo_silence_still_ok(monkeypatch, tmp_path) -> None:
    """Feed-fresh SoC must not hit Lesefehler via the live VO 30s silence window."""
    from runtime_store import loxone_push_inbox as inbox

    eid = "ess.15_kwh_speicher.sens_ess_soc"
    feed = tmp_path / "feed"
    # SoC push ~45s ago: past 3×10s VO silence, still within feed max_age (120s).
    _write_feed(
        feed,
        {
            f"loxone:io:{eid}": {
                "key": f"loxone:io:{eid}",
                "ts": _utc(-45),
                "ok": True,
                "status": None,
                "payload": {"LL": {"value": "14.0"}},
                "error": None,
            },
            "loxone:io:heartbeat": {
                "key": "loxone:io:heartbeat",
                "ts": _utc(-45),
                "ok": True,
                "status": None,
                "payload": {"LL": {"value": "1"}},
                "error": None,
            },
        },
        heartbeat_offset=0,
        cycle_offset=0,
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    inbox.reset_memory_for_tests()
    value, state = inbox.read_push_value(eid)
    assert (value, state) == (14.0, inbox.STATE_OK)


def test_shadow_read_push_value_ignores_prod_inbox_file(monkeypatch, tmp_path) -> None:
    """R2 hard cut: feed miss must not rescue from shared Prod inbox file."""
    from runtime_store import loxone_push_inbox as inbox

    eid = "ess.15_kwh_speicher.sens_ess_soc"
    earnie_env = tmp_path / "earnie_env"
    feed = earnie_env / "config" / "shadow_feed"
    prod_rt = earnie_env / "runtime"
    prod_rt.mkdir(parents=True)
    _write_feed(feed, {})  # no loxone keys
    (prod_rt / "loxone_push_inbox.json").write_text(
        json.dumps(
            {
                "signals": {
                    eid: {
                        "value": 17.0,
                        "raw": "17",
                        "parse_ok": True,
                        "last_ts": _utc(),
                        "count": 3,
                    },
                    "heartbeat": {
                        "value": 1.0,
                        "raw": "1",
                        "parse_ok": True,
                        "last_ts": _utc(),
                        "count": 10,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "shadow_runtime"))
    inbox.reset_memory_for_tests()
    value, state = inbox.read_push_value(eid)
    assert value != 17.0
    assert value is None or state != inbox.STATE_OK


def test_shadow_ready_by_time_from_feed(monkeypatch, tmp_path) -> None:
    """FertigUm comes from ``loxone:io:*`` feed only (no Prod inbox file)."""
    from runtime_store import loxone_push_inbox as inbox

    eid = "ev.e_auto.get_evcs_ready_by_time"
    feed = tmp_path / "feed"
    _write_feed(
        feed,
        {
            f"loxone:io:{eid}": {
                "key": f"loxone:io:{eid}",
                "ts": _utc(),
                "ok": True,
                "status": None,
                "payload": {"LL": {"value": "Morgen, 07:00"}},
                "error": None,
            }
        },
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "shadow_runtime"))
    inbox.reset_memory_for_tests()
    assert inbox.read_push_ready_by_time(eid) == "Morgen, 07:00"


def test_shadow_ready_by_time_ignores_prod_inbox_file(monkeypatch, tmp_path) -> None:
    """Feed miss must not read FertigUm from Prod ``loxone_push_inbox.json``."""
    from runtime_store import loxone_push_inbox as inbox

    eid = "ev.e_auto.get_evcs_ready_by_time"
    earnie_env = tmp_path / "earnie_env"
    feed = earnie_env / "config" / "shadow_feed"
    prod_rt = earnie_env / "runtime"
    prod_rt.mkdir(parents=True)
    _write_feed(feed, {})
    (prod_rt / "loxone_push_inbox.json").write_text(
        json.dumps(
            {
                "signals": {
                    eid: {
                        "value": None,
                        "raw": "Morgen, 07:00",
                        "parse_ok": False,
                        "last_ts": _utc(),
                        "count": 3,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "shadow_runtime"))
    inbox.reset_memory_for_tests()
    assert inbox.read_push_ready_by_time(eid) is None
