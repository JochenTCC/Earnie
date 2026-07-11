"""Tests für konfigurierbare UI-Fragment-Refresh-Intervalle."""
from __future__ import annotations

import pytest

import config
from tests.config_fixtures import write_minimal_config_tree
from ui import fragment_refresh


def _write_config(tmp_path, ui_block: dict | None) -> str:
    extra = {"ui": ui_block} if ui_block is not None else None
    payload = __import__("tests.config_fixtures", fromlist=["minimal_config_payload"]).minimal_config_payload(
        extra=extra
    )
    config_path, scenarios_path = write_minimal_config_tree(tmp_path, config_payload=payload)
    return config_path


def test_ui_fragment_defaults_without_ui_block(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_FRAGMENT_STATUS_SEC", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_MAIN_SYNC_POLL_SEC", raising=False)
    config_path, scenarios_path = write_minimal_config_tree(tmp_path)
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    assert cfg.get_ui_fragment_charts_sec() == 60
    assert cfg.get_ui_fragment_status_sec() == 10
    assert cfg.get_ui_main_sync_poll_sec() == 15


def test_ui_fragment_from_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC", raising=False)
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_FRAGMENT_STATUS_SEC", raising=False)
    from tests.config_fixtures import minimal_config_payload

    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(
            extra={"ui": {"fragment_refresh_charts_sec": 45, "fragment_refresh_status_sec": 5}}
        ),
    )
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    assert cfg.get_ui_fragment_charts_sec() == 45
    assert cfg.get_ui_fragment_status_sec() == 5


def test_env_overrides_config(monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC", "90")
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_FRAGMENT_STATUS_SEC", "15")
    assert fragment_refresh.charts_fragment_interval_sec() == 90
    assert fragment_refresh.status_fragment_interval_sec() == 15


def test_main_sync_poll_env_override(monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_MAIN_SYNC_POLL_SEC", "20")
    assert fragment_refresh.main_sync_poll_interval_sec() == 20


def test_invalid_env_raises(monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC", "0")
    with pytest.raises(ValueError, match="mindestens 1"):
        fragment_refresh.charts_fragment_interval_sec()
