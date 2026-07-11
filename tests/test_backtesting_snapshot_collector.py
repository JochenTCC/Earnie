"""Engine-Integration: Snapshot-Sammlung bei kritischen Fenstern."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from simulation import engine
from simulation.engine import PlausibilityResult, run_simulation
from simulation.horizon_mode import FIXED_24H
from tests.fixtures.backtesting_fixtures import (
    SOC_CHAIN_END_DAY,
    SOC_CHAIN_START_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")


class TestSnapshotCollector:
    @pytest.fixture(autouse=True)
    def _fixtures(self, monkeypatch):
        with activate_backtesting_fixtures(monkeypatch):
            yield

    def test_run_simulation_collects_snapshot_on_plausibility_failure(self, monkeypatch):
        original = engine.validate_window_consumption

        def _always_fail(chart_rows, meta):
            result = original(chart_rows, meta)
            return PlausibilityResult(
                window_end=result.window_end,
                historical_kwh=result.historical_kwh,
                optimized_kwh=result.optimized_kwh,
                diff_kwh=result.diff_kwh,
                ok=False,
                historical_baseload_kwh=result.historical_baseload_kwh,
                optimized_baseload_kwh=result.optimized_baseload_kwh,
                historical_flex_kwh=result.historical_flex_kwh,
                optimized_flex_kwh=result.optimized_flex_kwh,
                baseload_diff_kwh=result.baseload_diff_kwh,
                flex_diff_kwh=result.flex_diff_kwh,
            )

        monkeypatch.setattr(engine, "validate_window_consumption", _always_fail)

        cache = load_fixture_cache()
        scenario = fixture_scenario_params()
        prices = build_synthetic_prices_df(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
        )
        snapshots: list[dict] = []
        run_simulation(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
            scenario,
            prices,
            cache=cache,
            scenario_id="live",
            horizon_mode=FIXED_24H,
            snapshot_collector=snapshots,
        )
        assert len(snapshots) == 2
        assert snapshots[0]["scenario_id"] == "live"
        assert snapshots[0]["horizon_mode"] == FIXED_24H
        assert len(snapshots[0]["chart_rows_24h"]) == 24
