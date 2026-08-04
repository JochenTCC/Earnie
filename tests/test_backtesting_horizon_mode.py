"""Tests für Backtesting --horizon-mode (fixed_24h vs sunrise_window)."""
from __future__ import annotations

import os
import time

import pandas as pd
import pytest

from simulation.backtesting_horizon import (
    compute_sunrise_planning_at_anchor,
    effective_sunrise_soc_min_index,
    overlay_step_consumption_on_matrix,
    truncate_matrix_for_step_simulation,
)
from simulation.engine import (
    build_historical_window_matrix,
    build_sunrise_window_matrix,
    list_simulation_anchors,
    run_simulation,
    window_anchor_for_date,
)
from simulation.horizon_mode import (
    BACKTESTING_STEP_HOURS,
    FIXED_24H,
    SUNRISE_WINDOW,
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

os.environ.setdefault("EARNIE_OFFLINE", "1")

JUNE_SAMPLE_DAYS = tuple(pd.date_range("2026-06-23", "2026-06-25", freq="D"))


class TestParseHorizonMode:
    def test_accepts_fixed_24h(self):
        assert parse_horizon_mode("fixed_24h") == FIXED_24H

    def test_accepts_sunrise_window(self):
        assert parse_horizon_mode("sunrise_window") == SUNRISE_WINDOW

    def test_rejects_unknown_mode(self):
        with pytest.raises(ValueError, match="Ungültiger horizon_mode"):
            parse_horizon_mode("rolling_24h")


class TestEffectiveSunriseSocMinIndex:
    def test_within_step_passthrough(self):
        assert effective_sunrise_soc_min_index(0) == 0
        assert effective_sunrise_soc_min_index(23) == 23

    def test_at_or_beyond_step_returns_none(self):
        assert effective_sunrise_soc_min_index(BACKTESTING_STEP_HOURS) is None
        assert effective_sunrise_soc_min_index(BACKTESTING_STEP_HOURS + 1) is None

    def test_none_idempotent(self):
        assert effective_sunrise_soc_min_index(None) is None
        assert (
            effective_sunrise_soc_min_index(
                effective_sunrise_soc_min_index(BACKTESTING_STEP_HOURS)
            )
            is None
        )


class TestSunriseBacktestingRun:
    @pytest.fixture(autouse=True)
    def _fixtures(self, monkeypatch):
        with activate_backtesting_fixtures(monkeypatch):
            yield

    def test_two_day_sunrise_run_completes(self):
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
            horizon_mode=SUNRISE_WINDOW,
        )
        # Two abutting sunrise books (~24h each; DST/astronomy may vary ±1h).
        assert 44 <= len(df) <= 52
        assert plausibility.failed == []
        assert df["sim_soc"].notna().all()

    def test_fixed_and_sunrise_near_same_output_length(self):
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
        df_sunrise, _, _ = run_simulation(
            start, end, scenario, prices, cache=cache, horizon_mode=SUNRISE_WINDOW
        )
        assert len(df_fixed) == 48
        assert abs(len(df_sunrise) - len(df_fixed)) <= 4


class TestSunriseHorizonSizing:
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
            window, _ = compute_sunrise_planning_at_anchor(anchor, scenario)
            lengths.append(len(window.slot_datetimes))
        assert min(lengths) > BACKTESTING_STEP_HOURS
        assert max(lengths) <= BACKTESTING_STEP_HOURS + 24

    def test_sunrise_index_within_or_at_output_boundary(self):
        scenario = fixture_scenario_params()
        outside = 0
        for day in JUNE_SAMPLE_DAYS:
            anchor = window_anchor_for_date(day.date())
            _, sunrise_index = compute_sunrise_planning_at_anchor(anchor, scenario)
            if sunrise_index >= BACKTESTING_STEP_HOURS:
                outside += 1
        assert outside == 0, "Sommer-Fixture: Sonnenaufgang erwartet innerhalb 24h"

    def test_book_slice_shorter_than_full_milp_matrix(self):
        scenario = fixture_scenario_params()
        cache = load_fixture_cache()
        prices = build_synthetic_prices_df(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
        )
        anchor = window_anchor_for_date(SOC_CHAIN_START_DAY)
        matrix, meta, sa1_index, matrix_full = build_sunrise_window_matrix(
            anchor, cache, prices, scenario
        )
        assert meta["planning_horizon_hours"] == len(matrix_full)
        assert len(matrix_full) > len(matrix)
        assert len(matrix) == meta["book_hours"]
        assert 23 <= len(matrix) <= 25
        assert sa1_index == meta["sa1_index"]
        assert meta["ready_by"] == anchor

    def test_sunrise_book_slots_differ_from_fixed_ready_by_window(self):
        """Sunrise books [SA₁, SA₂); fixed_24h books [ready_by−24h, ready_by)."""
        scenario = fixture_scenario_params()
        cache = load_fixture_cache()
        prices = build_synthetic_prices_df(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
        )
        anchor = window_anchor_for_date(SOC_CHAIN_START_DAY)
        fixed_matrix, _fixed_meta = build_historical_window_matrix(
            anchor, cache, prices
        )
        sunrise_matrix, sunrise_meta, _, _matrix_full = build_sunrise_window_matrix(
            anchor, cache, prices, scenario
        )
        fixed_slots = [r["slot_datetime"] for r in fixed_matrix]
        sunrise_slots = [r["slot_datetime"] for r in sunrise_matrix]
        assert sunrise_slots != fixed_slots
        assert sunrise_meta["sa1"] is not None
        assert sunrise_meta["sa2"] is not None
        assert all(row.get("charging_anchor") == anchor for row in sunrise_matrix)


class TestOverlayStepConsumption:
    def test_overlay_copies_baseload_by_slot(self):
        step = [
            {
                "slot_datetime": pd.Timestamp("2025-01-09 07:00:00"),
                "expected_p_act": 1.1,
                "expected_p_total": 2.2,
            }
        ]
        output = [
            {
                "slot_datetime": pd.Timestamp("2025-01-09 07:00:00"),
                "expected_p_act": 0.5,
                "expected_p_total": 0.6,
            }
        ]
        overlay_step_consumption_on_matrix(output, step)
        assert output[0]["expected_p_act"] == 1.1
        assert output[0]["expected_p_total"] == 2.2


class TestSunriseBacktestingRuntime:
    """Kurz-Benchmark: sunrise_window darf nicht deutlich langsamer als fixed_24h sein."""

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
            start, end, scenario, prices, cache=cache, horizon_mode=SUNRISE_WINDOW
        )
        sunrise_sec = time.perf_counter() - t0

        assert fixed_sec < 120.0, f"fixed_24h Referenz zu langsam: {fixed_sec:.1f}s"
        assert sunrise_sec < 120.0, f"sunrise_window zu langsam: {sunrise_sec:.1f}s"
        assert sunrise_sec < fixed_sec * 2.5 + 5.0, (
            f"sunrise_window ({sunrise_sec:.1f}s) >> fixed_24h ({fixed_sec:.1f}s) — "
            "prüfe Matrix-Truncation vor simulate_horizon"
        )
