# tests/test_backtesting_time_ranges.py
"""Tests für Backtesting-Zeitraum-Hilfen in der UI."""
from __future__ import annotations

from datetime import date

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
        "ui.backtesting_time_ranges.config.get_scenario_explorer_conf",
        lambda: {"price_range": "last_12_months"},
    )
    assert configured_price_range() == "last_12_months"
    assert "12 Kalendermonate" in describe_price_range("last_12_months")


def test_default_simulation_window_month_aligned(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_time_ranges.config.get_scenario_explorer_conf",
        lambda: {"price_range": "last_12_months"},
    )
    monkeypatch.setattr(
        "data.profile_manager.get_cons_data_date_bounds",
        lambda: (date(2025, 1, 15), date(2026, 6, 25)),
    )
    start, end = default_simulation_window()
    assert end == date(2026, 5, 31)
    assert start == date(2025, 6, 1)


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
