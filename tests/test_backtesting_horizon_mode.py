"""Tests für Backtesting --horizon-mode (fixed_24h vs sunset_window)."""
from __future__ import annotations

import os
import time

import pandas as pd
import pytest

from simulation.backtesting_horizon import (
    compute_sunset_planning_at_anchor,
    truncate_matrix_for_step_simulation,
)
from simulation.engine import (
    build_sunset_window_matrix,
    list_simulation_anchors,
    run_simulation,
    window_anchor_for_date,
)
from simulation.horizon_mode import (
    BACKTESTING_STEP_HOURS,
    FIXED_24H,
    SUNSET_WINDOW,
    parse_horizon_mode,
)
from tests.fixtures.backtesting_fixtures import (
    SOC_CHAIN_END_DAY,
    SOC_CHAIN_START_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

JUNE_SAMPLE_DAYS = tuple(pd.date_range("2026-06-23", "2026-06-25", freq="D"))


class TestParseHorizonMode:
    def test_accepts_fixed_24h(self):
        assert parse_horizon_mode("fixed_24h") == FIXED_24H

    def test_accepts_sunset_window(self):
        assert parse_horizon_mode("sunset_window") == SUNSET_WINDOW

    def test_rejects_unknown_mode(self):
        with pytest.raises(ValueError, match="Ungültiger horizon_mode"):
            parse_horizon_mode("rolling_24h")


class TestSunsetBacktestingRun:
    @pytest.fixture(autouse=True)
    def _fixtures(self, monkeypatch):
        with activate_backtesting_fixtures(monkeypatch):
            yield

    def test_two_day_sunset_run_completes(self):
        cache = load_fixture_cache()
        scenario = fixture_scenario_params()
        prices = build_synthetic_prices_df(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
        )
        start = pd.Timestamp(SOC_CHAIN_START_DAY)
        end = pd.Timestamp(SOC_CHAIN_END_DAY)
        anchors = list_simulation_anchors(start, end, cache)
        assert len(anchors) == 2

        df, plausibility, _ = run_simulation(
            start,
            end,
            scenario,
            prices,
            cache=cache,
            initial_soc=50.0,
            horizon_mode=SUNSET_WINDOW,
        )
        assert len(df) == 48
        assert plausibility.failed == []
        assert df["sim_soc"].notna().all()

    def test_fixed_and_sunset_produce_same_output_length(self):
        cache = load_fixture_cache()
        scenario = fixture_scenario_params()
        prices = build_synthetic_prices_df(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
        )
        start = pd.Timestamp(SOC_CHAIN_START_DAY)
        end = pd.Timestamp(SOC_CHAIN_END_DAY)

        df_fixed, _, _ = run_simulation(
            start, end, scenario, prices, cache=cache, horizon_mode=FIXED_24H
        )
        df_sunset, _, _ = run_simulation(
            start, end, scenario, prices, cache=cache, horizon_mode=SUNSET_WINDOW
        )
        assert len(df_fixed) == len(df_sunset) == 48


class TestSunsetHorizonSizing:
    """Diagnose: volle SA₂-Matrix vs. 24h-Output — Ursache für Laufzeit-Unterschied."""

    @pytest.fixture(autouse=True)
    def _fixtures(self, monkeypatch):
        with activate_backtesting_fixtures(monkeypatch):
            yield

    def test_full_planning_matrix_longer_than_output_step(self):
        scenario = fixture_scenario_params()
        lengths = []
        for day in JUNE_SAMPLE_DAYS:
            anchor = window_anchor_for_date(day.date())
            window, _ = compute_sunset_planning_at_anchor(anchor, scenario)
            lengths.append(len(window.slot_datetimes))
        assert min(lengths) > BACKTESTING_STEP_HOURS
        assert max(lengths) <= BACKTESTING_STEP_HOURS + 20

    def test_sunrise_index_within_output_step(self):
        scenario = fixture_scenario_params()
        for day in JUNE_SAMPLE_DAYS:
            anchor = window_anchor_for_date(day.date())
            _, sunrise_index = compute_sunset_planning_at_anchor(anchor, scenario)
            assert sunrise_index < BACKTESTING_STEP_HOURS

    def test_truncation_limits_simulation_to_output_step(self):
        scenario = fixture_scenario_params()
        cache = load_fixture_cache()
        prices = build_synthetic_prices_df(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
        )
        anchor = window_anchor_for_date(SOC_CHAIN_START_DAY)
        matrix, meta, sunrise_index = build_sunset_window_matrix(
            anchor, cache, prices, scenario
        )
        assert meta["planning_horizon_hours"] > BACKTESTING_STEP_HOURS
        assert len(matrix) == BACKTESTING_STEP_HOURS


class TestSunsetBacktestingRuntime:
    """Kurz-Benchmark: sunset_window darf nicht deutlich langsamer als fixed_24h sein."""

    @pytest.fixture(autouse=True)
    def _fixtures(self, monkeypatch):
        with activate_backtesting_fixtures(monkeypatch):
            yield

    def test_two_window_modes_comparable_runtime(self):
        cache = load_fixture_cache()
        scenario = fixture_scenario_params()
        start = pd.Timestamp(SOC_CHAIN_START_DAY)
        end = pd.Timestamp(SOC_CHAIN_END_DAY)
        prices = build_synthetic_prices_df(start, end)
        anchors = list_simulation_anchors(start, end, cache)
        assert len(anchors) == 2

        t0 = time.perf_counter()
        run_simulation(
            start, end, scenario, prices, cache=cache, horizon_mode=FIXED_24H
        )
        fixed_sec = time.perf_counter() - t0

        t0 = time.perf_counter()
        run_simulation(
            start, end, scenario, prices, cache=cache, horizon_mode=SUNSET_WINDOW
        )
        sunset_sec = time.perf_counter() - t0

        assert fixed_sec < 120.0, f"fixed_24h Referenz zu langsam: {fixed_sec:.1f}s"
        assert sunset_sec < 120.0, f"sunset_window zu langsam: {sunset_sec:.1f}s"
        assert sunset_sec < fixed_sec * 2.5 + 5.0, (
            f"sunset_window ({sunset_sec:.1f}s) >> fixed_24h ({fixed_sec:.1f}s) — "
            "prüfe Matrix-Truncation vor simulate_horizon"
        )
