"""Shadow write block, config read-only, seed script."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from integrations.loxone_writes import _send_loxone_value_traced
from runtime_store.shadow import feed as shadow_feed
from runtime_store.shadow.errors import ConfigReadOnlyError
from runtime_store.shadow.writes import read_shadow_writes
from scripts.shadow_seed_runtime import seed_runtime
from settings.json_io import write_json_dict


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    shadow_feed.reset_for_tests()
    yield
    shadow_feed.reset_for_tests()


def test_loxone_write_blocked_and_logged(monkeypatch, tmp_path):
    runtime = tmp_path / "rt"
    runtime.mkdir()
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(runtime))
    record = _send_loxone_value_traced("Earnie_Mode", 1.0)
    assert record.success is False
    rows = read_shadow_writes()
    assert len(rows) == 1
    assert rows[0]["backend"] == "loxone"
    assert rows[0]["target"] == "Earnie_Mode"
    assert rows[0]["value"] == 1.0


def test_config_write_raises_in_shadow(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    target = cfg_dir / "config.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(cfg_dir))
    with pytest.raises(ConfigReadOnlyError):
        write_json_dict(str(target), {"earnie_data_model": 3})


def test_silent_implied_by_shadow(monkeypatch, tmp_path):
    import config
    from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree

    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path, config_payload=minimal_config_payload()
    )
    local_path = tmp_path / "local_settings.json"
    local_path.write_text(json.dumps({"silent_mode": False}), encoding="utf-8")
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    monkeypatch.setattr(config, "CONFIG", cfg)
    assert cfg.is_silent_mode() is False
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    assert cfg.is_silent_mode() is True


def test_ha_secrets_migration_skipped_in_shadow(monkeypatch):
    from runtime_store import ha_secrets_migrate

    monkeypatch.setenv("EARNIE_SHADOW", "1")
    assert ha_secrets_migrate.apply_ha_secrets_migration_to_disk() is False


def test_shadow_seed_runtime_copies_and_excludes(tmp_path):
    src = tmp_path / "prod"
    dst = tmp_path / "shadow"
    src.mkdir()
    (src / "optimization_history.jsonl").write_text("{}\n", encoding="utf-8")
    (src / "cons_data.csv").write_text("a,b\n", encoding="utf-8")
    (src / "earnie.log").write_text("log\n", encoding="utf-8")
    (src / "local_settings.json").write_text("{}", encoding="utf-8")
    (src / "main.lock").write_text("1", encoding="utf-8")
    copied = seed_runtime(src=src, dst=dst)
    assert (dst / "optimization_history.jsonl").is_file()
    assert (dst / "cons_data.csv").is_file()
    assert (dst / ".shadow_runtime").is_file()
    assert not (dst / "earnie.log").exists()
    assert not (dst / "local_settings.json").exists()
    assert not (dst / "main.lock").exists()
    assert any("optimization_history" in p for p in copied)
