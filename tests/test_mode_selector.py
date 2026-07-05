"""Tests für UI-Modus-Auswahl (Prod vs. Dev)."""
from __future__ import annotations

from ui.mode_selector import UI_MODE_KEYS, get_enabled_ui_modes


def test_default_modes_exclude_historical(monkeypatch):
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_MODES", raising=False)
    modes = get_enabled_ui_modes()
    assert modes == ["Sunset-2-Sunset", "Backtesting"]
    assert "Historischer Tag" not in modes


def test_prod_modes_from_env(monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_MODES", "sunset2sunset,backtesting")
    assert get_enabled_ui_modes() == ["Sunset-2-Sunset", "Backtesting"]


def test_historical_in_env_is_ignored(monkeypatch):
    monkeypatch.setenv(
        "ENERGY_OPTIMIZER_UI_MODES", "sunset2sunset,historical,backtesting"
    )
    modes = get_enabled_ui_modes()
    assert "Historischer Tag" not in modes
    assert modes == ["Sunset-2-Sunset", "Backtesting"]


def test_ui_mode_keys_has_no_historical():
    assert "historical" not in UI_MODE_KEYS
