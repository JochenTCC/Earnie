"""Tests for Shadow Mode S1 Prod feed recorder (2.6.o)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import config
import pytest
from runtime_store.shadow import feed as shadow_feed
from runtime_store.shadow import is_shadow_mode
from runtime_store.shadow.hooks import record_transport
from runtime_store.shadow.superset import run_after_cycle
from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree


@pytest.fixture(autouse=True)
def _reset_shadow(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    # Prefer "0" over delenv: survives leaked parent/worker EARNIE_SHADOW=1.
    monkeypatch.setenv("EARNIE_SHADOW", "0")
    monkeypatch.delenv("EARNIE_SHADOW_FEED_PATH", raising=False)
    shadow_feed.reset_for_tests()
    yield
    shadow_feed.reset_for_tests()


def _enable_feed(tmp_path, monkeypatch, *, retention_days: int = 14) -> Path:
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(),
    )
    local_path = tmp_path / "local_settings.json"
    local_path.write_text(
        json.dumps(
            {
                "silent_mode": True,
                "shadow_feed_enabled": True,
                "shadow_feed_retention_days": retention_days,
            }
        ),
        encoding="utf-8",
    )
    feed_path = tmp_path / "shadow_feed"
    monkeypatch.setenv("EARNIE_SHADOW", "0")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed_path))
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(Path(config_path).parent))
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    monkeypatch.setattr(config, "CONFIG", cfg)
    assert cfg.is_shadow_feed_enabled() is True
    assert is_shadow_mode() is False
    assert shadow_feed.is_feed_recording_enabled() is True
    assert shadow_feed.feed_dir() == feed_path
    return feed_path


def test_is_shadow_mode_false_without_env():
    assert is_shadow_mode() is False


def test_is_shadow_mode_true_with_env(monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    assert is_shadow_mode() is True


def test_recording_disabled_by_default(tmp_path, monkeypatch):
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path, config_payload=minimal_config_payload()
    )
    local_path = tmp_path / "local_settings.json"
    local_path.write_text(json.dumps({"silent_mode": True}), encoding="utf-8")
    feed_path = tmp_path / "shadow_feed"
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed_path))
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    monkeypatch.setattr(config, "CONFIG", cfg)
    record_transport("loxone:io:X", ok=True, payload={"LL": {"value": "1"}})
    assert not feed_path.exists()


def test_shadow_env_disables_recorder(tmp_path, monkeypatch, caplog):
    feed_path = _enable_feed(tmp_path, monkeypatch)
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    feed_logger = logging.getLogger("runtime_store.shadow.feed")
    with caplog.at_level(logging.WARNING, logger=feed_logger.name):
        assert is_shadow_mode() is True
        assert shadow_feed.is_feed_recording_enabled() is False
        assert shadow_feed.is_feed_recording_enabled() is False
    record_transport("loxone:io:X", ok=True, payload={"v": 1})
    assert not list(feed_path.glob("*"))
    warnings = [r for r in caplog.records if "EARNIE_SHADOW" in r.getMessage()]
    assert len(warnings) == 1


def test_record_ok_and_error_jsonl_no_secrets(tmp_path, monkeypatch):
    feed_path = _enable_feed(tmp_path, monkeypatch)
    assert is_shadow_mode() is False
    assert shadow_feed.is_feed_recording_enabled() is True
    record_transport(
        "ha:get:/api/states/sensor.x",
        ok=True,
        payload={"state": "1.2", "attributes": {"unit_of_measurement": "kW"}},
        status=200,
    )
    record_transport(
        "loxone:io:Earnie_SOC",
        ok=False,
        status=401,
        error="unauthorized",
    )
    shadow_feed.flush_after_cycle()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jsonl_path = feed_path / f"feed-{day}.jsonl"
    assert jsonl_path.is_file(), f"missing {jsonl_path}; feed_dir={shadow_feed.feed_dir()}"
    jsonl = jsonl_path.read_text(encoding="utf-8")
    assert "Authorization" not in jsonl
    assert "password" not in jsonl.lower()
    assert "token" not in jsonl.lower()
    assert "ha:get:/api/states/sensor.x" in jsonl
    assert "loxone:io:Earnie_SOC" in jsonl
    latest = json.loads((feed_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["cycle_seq"] == 1
    assert "ha:get:/api/states/sensor.x" in latest["records"]
    meta = json.loads((feed_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["feed_schema"] == 1
    assert meta["cycle_seq"] == 1


def test_atomic_latest_and_retention(tmp_path, monkeypatch):
    feed_path = _enable_feed(tmp_path, monkeypatch, retention_days=2)
    old = feed_path / "feed-2000-01-01.jsonl"
    feed_path.mkdir(parents=True)
    old.write_text("{}\n", encoding="utf-8")
    recent_day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    recent = feed_path / f"feed-{recent_day}.jsonl"
    recent.write_text("{}\n", encoding="utf-8")
    record_transport("ext:prices:energy_charts", ok=True, payload={"price": [1]})
    shadow_feed.flush_after_cycle()
    assert not old.exists()
    assert recent.exists()
    assert (feed_path / "latest.json").is_file()


def test_recorder_exception_swallowed(tmp_path, monkeypatch):
    _enable_feed(tmp_path, monkeypatch)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(shadow_feed, "_append_jsonl_unlocked", boom)
    record_transport("loxone:io:Y", ok=True, payload="1")  # must not raise


def _patch_ha_superset(monkeypatch, *, adapter, entities: dict[str, str]) -> None:
    """Route superset to HA without stubbing ``config.get`` (breaks other keys)."""
    import integrations.ehal_live as ehal_live
    import runtime_store.shadow.superset as superset_mod

    monkeypatch.setattr(config.CONFIG, "EHAL_BACKEND", "ha", raising=False)
    monkeypatch.setattr(superset_mod, "_house_profiles_doc", lambda: {})
    monkeypatch.setattr(
        "house_config.ha_ehal_bindings.aggregate_ha_entities",
        lambda _h: entities,
    )
    monkeypatch.setattr(ehal_live, "get_ha_adapter", lambda: adapter)


def test_superset_ha_fetches_missing(tmp_path, monkeypatch):
    _enable_feed(tmp_path, monkeypatch)
    record_transport(
        "ha:get:/api/states/sensor.soc",
        ok=True,
        payload={"state": "50"},
        status=200,
    )
    adapter = MagicMock()
    adapter.read_state = MagicMock(return_value={"state": "100", "attributes": {}})
    _patch_ha_superset(
        monkeypatch,
        adapter=adapter,
        entities={
            "sens_ess_soc": "sensor.soc",
            "sens_grid_power_active": "sensor.grid",
        },
    )

    run_after_cycle(budget_sec=5)
    called_ids = [c.args[0] for c in adapter.read_state.call_args_list]
    assert "sensor.grid" in called_ids
    assert "sensor.soc" not in called_ids


def test_superset_budget_stops_early(tmp_path, monkeypatch):
    _enable_feed(tmp_path, monkeypatch)
    house_bindings = {f"sensor.e{i}": f"sensor.e{i}" for i in range(20)}
    calls: list[str] = []
    clock = {"t": 1000.0}

    class BudgetAdapter:
        def read_state(self, entity_id):
            calls.append(entity_id)
            clock["t"] += 0.05
            return {"state": "1"}

    import runtime_store.shadow.superset as superset_mod

    monkeypatch.setattr(superset_mod.time, "monotonic", lambda: clock["t"])
    _patch_ha_superset(monkeypatch, adapter=BudgetAdapter(), entities=house_bindings)
    run_after_cycle(budget_sec=0.12)
    assert 0 < len(calls) < 20


def test_packaging_trees_lack_earnie_shadow():
    root = Path(__file__).resolve().parents[1]
    hits = []
    for rel in ("packaging", "docker"):
        base = root / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "EARNIE_SHADOW=" in text or "EARNIE_SHADOW:" in text:
                hits.append(str(path.relative_to(root)))
    assert hits == []
