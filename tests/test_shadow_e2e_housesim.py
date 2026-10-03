"""HouseSim as Prod backend → Shadow replay (no Shadow backend HTTP)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from house_sim.archetype import load_archetype, project_physics_to_store
from house_sim.mock_rest import DEFAULT_BENCH_TOKEN, start_mock_rest, stop_mock_rest
from house_sim.stepper import initial_physics
from integrations.ha_adapter import HaAdapter, HaConfig
from runtime_store.shadow import feed as shadow_feed
from runtime_store.shadow import reader as shadow_reader
from runtime_store.shadow import replay as shadow_replay
from runtime_store.shadow.hooks import record_transport


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.delenv("EARNIE_SHADOW_FEED_PATH", raising=False)
    shadow_feed.reset_for_tests()
    shadow_reader.reset_reader_for_tests()
    shadow_replay.reset_replay_for_tests()
    yield
    shadow_feed.reset_for_tests()
    stop_mock_rest()


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def test_housesim_prod_records_and_shadow_replays(monkeypatch, tmp_path):
    package = load_archetype("evcc_en")
    store = package.build_store()
    physics = initial_physics(package)
    project_physics_to_store(store, package=package, physics=physics.as_dict())
    _server, base_url = start_mock_rest(
        store, host="127.0.0.1", port=0, token=DEFAULT_BENCH_TOKEN
    )
    entities = dict(package.ehal_entities)
    prod = HaAdapter(
        HaConfig(
            base_url=base_url,
            token=DEFAULT_BENCH_TOKEN,
            adapter_id="earnie-hems",
            entities=entities,
            sign=dict(package.ehal_sign),
        )
    )

    # Simulate Prod recorder: capture live reads into a feed file Shadow will read.
    feed = tmp_path / "shadow_feed"
    feed.mkdir()
    records: dict = {}
    for field, entity_id in list(entities.items())[:6]:
        if not entity_id:
            continue
        path = f"/api/states/{entity_id}"
        payload = prod._get_json(path)
        key = f"ha:get:{path}"
        records[key] = {
            "key": key,
            "ts": _utc(),
            "ok": True,
            "status": 200,
            "payload": payload,
            "error": None,
        }
        record_transport(key, ok=True, payload=payload, status=200)

    hb = _utc()
    (feed / "meta.json").write_text(
        json.dumps(
            {
                "feed_schema": 1,
                "earnie_version": "2.6.0",
                "earnie_data_model": 4,
                "ehal_backend": "ha",
                "prod_runtime_dir": str(tmp_path / "prod_rt"),
                "heartbeat_ts": hb,
                "cycle_seq": 1,
            }
        ),
        encoding="utf-8",
    )
    (feed / "latest.json").write_text(
        json.dumps({"cycle_seq": 1, "cycle_ts": hb, "records": records}),
        encoding="utf-8",
    )

    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    shadow_reader.reset_reader_for_tests()

    shadow = HaAdapter(
        HaConfig(
            base_url="http://127.0.0.1:9",  # must not be contacted
            token="unused",
            adapter_id="earnie-hems",
            entities=entities,
            sign=dict(package.ehal_sign),
        )
    )
    get_spy = MagicMock(side_effect=AssertionError("Shadow must not call backend"))
    monkeypatch.setattr("integrations.ha_adapter.requests.get", get_spy)
    monkeypatch.setattr("integrations.ha_adapter.requests.post", get_spy)

    # Same entity payloads as Prod recorded
    for key, entry in records.items():
        path = key.removeprefix("ha:get:")
        assert shadow._get_json(path) == entry["payload"]
    get_spy.assert_not_called()

    # Write block
    from runtime_store.shadow.writes import block_write_if_shadow

    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "shadow_rt"))
    assert (
        block_write_if_shadow(
            backend="ha", target="sensor.x", value=1, source="e2e"
        )
        is True
    )
