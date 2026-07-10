# tests/test_persist_paths_sidecars.py
"""Tests für Sidecar-Pfad-Auflösung neben ENERGY_OPTIMIZER_CONFIG_PATH."""
from __future__ import annotations

from pathlib import Path

from runtime_store.persist_paths import (
    resolve_backtesting_log_dir,
    resolve_backtesting_scenarios_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
)


def test_sidecars_resolve_next_to_config_path(tmp_path, monkeypatch):
    config_dir = tmp_path / "greenfield" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    (config_dir / "tariffs.json").write_text("{}", encoding="utf-8")
    (config_dir / "house_profiles.json").write_text("{}", encoding="utf-8")
    (config_dir / "backtesting_scenarios.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.delenv("ENERGY_OPTIMIZER_TARIFFS_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH", raising=False)

    assert resolve_tariffs_json_path() == str(config_dir / "tariffs.json")
    assert resolve_house_profiles_json_path() == str(config_dir / "house_profiles.json")
    assert resolve_backtesting_scenarios_json_path() == str(
        config_dir / "backtesting_scenarios.json"
    )


def test_backtesting_log_dir_uses_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))
    assert resolve_backtesting_log_dir() == str(tmp_path / "runtime")


def test_explicit_sidecar_env_overrides_co_located(tmp_path, monkeypatch):
    config_dir = tmp_path / "cfg"
    other_dir = tmp_path / "other"
    config_dir.mkdir()
    other_dir.mkdir()
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    (config_dir / "tariffs.json").write_text('{"local": true}', encoding="utf-8")
    custom_tariffs = other_dir / "tariffs.json"
    custom_tariffs.write_text('{"custom": true}', encoding="utf-8")

    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv("ENERGY_OPTIMIZER_TARIFFS_PATH", str(custom_tariffs))

    assert resolve_tariffs_json_path() == str(custom_tariffs)


def test_sidecar_falls_back_to_default_config_when_missing_beside_config(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "isolated"
    config_dir.mkdir()
    (config_dir / "config.json").write_text("{}", encoding="utf-8")

    default_tariffs = tmp_path / "config" / "tariffs.json"
    default_tariffs.parent.mkdir()
    default_tariffs.write_text("{}", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.delenv("ENERGY_OPTIMIZER_TARIFFS_PATH", raising=False)

    resolved = resolve_tariffs_json_path()
    assert Path(resolved).resolve() == default_tariffs.resolve()
