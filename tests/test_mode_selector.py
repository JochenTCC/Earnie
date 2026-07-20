"""Tests für UI-Modus-Auswahl (Prod vs. Dev)."""
from __future__ import annotations

import config
from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree
from ui.mode_selector import UI_MODE_KEYS, get_enabled_ui_modes


def test_default_modes_exclude_historical_and_price_forecast(monkeypatch):
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_MODES", raising=False)
    monkeypatch.delenv("EARNIE_UI_MODES", raising=False)
    monkeypatch.setattr(
        "ui.mode_selector.config.get_ui_price_forecast_page_enabled",
        lambda: False,
    )
    modes = get_enabled_ui_modes()
    assert modes == [
        "Sunset-2-Sunset",
        "Szenario-Explorer",
        "Daemon Control",
    ]
    assert "Historischer Tag" not in modes
    assert "Preis-Prognose (Dev)" not in modes


def test_price_forecast_mode_when_config_enabled(monkeypatch):
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_MODES", raising=False)
    monkeypatch.delenv("EARNIE_UI_MODES", raising=False)
    monkeypatch.setattr(
        "ui.mode_selector.config.get_ui_price_forecast_page_enabled",
        lambda: True,
    )
    assert get_enabled_ui_modes() == [
        "Sunset-2-Sunset",
        "Szenario-Explorer",
        "Daemon Control",
        "Preis-Prognose (Dev)",
    ]


def test_prod_modes_from_env(monkeypatch):
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_UI_MODES",
        "sunset2sunset,scenario_explorer,live_environment",
    )
    assert get_enabled_ui_modes() == [
        "Sunset-2-Sunset",
        "Szenario-Explorer",
        "Daemon Control",
    ]


def test_historical_in_env_is_ignored(monkeypatch):
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_UI_MODES",
        "sunset2sunset,historical,scenario_explorer,live_environment",
    )
    modes = get_enabled_ui_modes()
    assert "Historischer Tag" not in modes
    assert modes == [
        "Sunset-2-Sunset",
        "Szenario-Explorer",
        "Daemon Control",
    ]


def test_ui_mode_keys_has_no_historical():
    assert "historical" not in UI_MODE_KEYS
    assert "live_environment" in UI_MODE_KEYS


def test_ui_price_forecast_page_default_false(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = write_minimal_config_tree(tmp_path)
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    assert cfg.get_ui_price_forecast_page_enabled() is False


def test_ui_price_forecast_page_from_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(
            extra={"ui": {"price_forecast_page_enabled": True}}
        ),
    )
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    assert cfg.get_ui_price_forecast_page_enabled() is True
