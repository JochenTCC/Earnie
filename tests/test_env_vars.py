"""Tests for EARNIE_* env var resolution."""
from __future__ import annotations

from runtime_store import env_vars


def test_read_env(monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", "/earnie/runtime")
    assert env_vars.read_env("RUNTIME_PATH") == "/earnie/runtime"


def test_read_env_or_default(monkeypatch):
    monkeypatch.delenv("EARNIE_RUNTIME_PATH", raising=False)
    assert env_vars.read_runtime_path_or("runtime") == "runtime"


def test_read_runtime_path_empty_without_env(monkeypatch):
    monkeypatch.delenv("EARNIE_RUNTIME_PATH", raising=False)
    assert env_vars.read_runtime_path() == ""


def test_is_truthy(monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    assert env_vars.is_truthy("OFFLINE") is True
    monkeypatch.setenv("EARNIE_OFFLINE", "0")
    assert env_vars.is_truthy("OFFLINE") is False


def test_is_explicit_offline(monkeypatch):
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
    assert env_vars.is_explicit_offline() is False
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    assert env_vars.is_explicit_offline() is True


def test_is_effective_offline_greenfield_gate(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv(
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(config_dir / "components.json"))
    monkeypatch.setenv("EARNIE_TARIFFS_PATH", str(config_dir / "tariffs.json"))
    monkeypatch.setenv(
        "EARNIE_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)

    (config_dir / "config.json").write_text(
        '{"flexible_consumers": [], "live_scenario_id": "live"}',
        encoding="utf-8",
    )
    (config_dir / "components.json").write_text(
        '{"batteries": [], "pv_systems": []}',
        encoding="utf-8",
    )
    (config_dir / "tariffs.json").write_text(
        '{"import_tariffs": [], "export_tariffs": []}',
        encoding="utf-8",
    )
    (config_dir / "house_profiles.json").write_text('{"profiles": []}', encoding="utf-8")
    (config_dir / "backtesting_scenarios.json").write_text(
        '{"scenarios": [{"id": "live", "settings": {}}]}',
        encoding="utf-8",
    )

    assert env_vars.is_planning_offline_gated() is True
    assert env_vars.is_effective_offline() is True
