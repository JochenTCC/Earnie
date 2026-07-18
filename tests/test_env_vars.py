"""Tests for EARNIE_* env var resolution with ENERGY_OPTIMIZER_* fallback."""
from __future__ import annotations

import pytest

from runtime_store import env_vars


def test_read_env_prefers_earnie_over_legacy(monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", "/earnie/runtime")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_PATH", "/legacy/runtime")
    assert env_vars.read_env("RUNTIME_PATH") == "/earnie/runtime"


def test_read_env_falls_back_to_legacy(monkeypatch):
    monkeypatch.delenv("EARNIE_RUNTIME_PATH", raising=False)
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_PATH", "/legacy/runtime")
    assert env_vars.read_env("RUNTIME_PATH") == "/legacy/runtime"


def test_read_env_or_default(monkeypatch):
    monkeypatch.delenv("EARNIE_RUNTIME_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_RUNTIME_PATH", raising=False)
    monkeypatch.delenv("EARNIE_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_RUNTIME_DIR", raising=False)
    assert env_vars.read_runtime_path_or("runtime") == "runtime"


def test_read_runtime_path_legacy_dir_fallback(monkeypatch):
    monkeypatch.delenv("EARNIE_RUNTIME_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_RUNTIME_PATH", raising=False)
    monkeypatch.setenv("EARNIE_RUNTIME_DIR", "/old/runtime")
    assert env_vars.read_runtime_path() == "/old/runtime"


def test_is_truthy(monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    assert env_vars.is_truthy("OFFLINE") is True
    monkeypatch.setenv("EARNIE_OFFLINE", "0")
    assert env_vars.is_truthy("OFFLINE") is False


def test_is_explicit_offline(monkeypatch):
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_OFFLINE", raising=False)
    assert env_vars.is_explicit_offline() is False
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    assert env_vars.is_explicit_offline() is True


def test_is_effective_offline_greenfield_gate(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    monkeypatch.setenv("ENERGY_OPTIMIZER_COMPONENTS_PATH", str(config_dir / "components.json"))
    monkeypatch.setenv("ENERGY_OPTIMIZER_TARIFFS_PATH", str(config_dir / "tariffs.json"))
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.delenv("ENERGY_OPTIMIZER_OFFLINE", raising=False)
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)

    (config_dir / "config.json").write_text(
        '{"flexible_consumers": [], "live_scenario_id": "live"}',
        encoding="utf-8",
    )
    (config_dir / "components.json").write_text('{"batteries": [], "pv_systems": []}', encoding="utf-8")
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
