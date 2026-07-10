# tests/test_backtesting_time_ranges.py
"""Tests für Backtesting-Zeitraum-Hilfen in der UI."""
from __future__ import annotations

from datetime import date

import pandas as pd

from ui.backtesting_time_ranges import (
    build_time_range_help_lines,
    cons_data_section_caption,
    configured_price_range,
    configured_retention_months,
    default_simulation_window,
    describe_price_range,
)


def test_configured_retention_months_from_sim_config(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.cons_data_store.get_retention_months",
        lambda: 24,
    )
    assert configured_retention_months() == 24


def test_configured_price_range_default(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.config.get_file_paths_battery_simulation",
        lambda: {"price_range": "last_12_months"},
    )
    assert configured_price_range() == "last_12_months"
    assert describe_price_range("last_12_months") == "rollierende 12 Monate bis heute"


def test_default_simulation_window_last_12_months(monkeypatch):
    fixed_today = pd.Timestamp("2026-07-10")
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.config.get_file_paths_battery_simulation",
        lambda: {
            "price_range": "last_12_months",
            "path_consumption": "c.csv",
            "path_production": "p.csv",
        },
    )
    monkeypatch.setattr(
        "data.data_loader.pd.Timestamp.now",
        lambda: fixed_today,
    )
    start, end = default_simulation_window()
    assert end == date(2026, 7, 10)
    assert start == date(2025, 7, 10)


def test_build_time_range_help_lines_without_log(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.configured_retention_months",
        lambda: 24,
    )
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.configured_price_range",
        lambda: "last_12_months",
    )
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.default_simulation_window",
        lambda: (date(2025, 7, 10), date(2026, 7, 10)),
    )
    lines = build_time_range_help_lines()
    assert len(lines) == 4
    assert "24" in lines[0]
    assert "last_12_months" in lines[1]
    assert "2025-07-10" in lines[1]
    assert "nach einem Lauf" in lines[2]
    assert "8760" in lines[3]


def test_build_time_range_help_lines_with_log_period(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.configured_retention_months",
        lambda: 24,
    )
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.configured_price_range",
        lambda: "last_12_months",
    )
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.default_simulation_window",
        lambda: (date(2025, 7, 10), date(2026, 7, 10)),
    )
    lines = build_time_range_help_lines(
        log_period={"start": "2025-06-01", "end": "2025-06-30"},
    )
    assert "2025-06-01" in lines[2]
    assert "letzten Laufs" in lines[2]


def test_cons_data_section_caption_mentions_retention(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.configured_retention_months",
        lambda: 24,
    )
    caption = cons_data_section_caption()
    assert "24" in caption
    assert "cons_data_retention_months" in caption
    assert "price_range" in caption
