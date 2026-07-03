"""Schnelle Integrationstests für den Backtesting-Pfad (ohne vollen Lauf)."""
from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

import config
from data.data_loader import load_market_prices
from optimizer.milp import milp_optimizer
from optimizer.charging_context import resolve_charging_context
from simulation.backtesting_log import load_backtesting_log, save_backtesting_log
from simulation.engine import (
    HISTORICAL_REFERENCE_ID,
    HistoricalDataCache,
    PlausibilityReport,
    compute_historical_reference_costs,
    run_simulation,
)
from tests.backtesting_case_selection import (
    DEFAULT_MAX_EAUTO_KWH,
    select_backtesting_smoke_anchor,
)
from tests.conftest import requires_historical_data

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

SMOKE_DAY = date(2026, 6, 25)


@pytest.fixture(scope="module")
def historical_cache() -> HistoricalDataCache:
    cache = HistoricalDataCache()
    cache.load()
    return cache


@pytest.fixture(scope="module")
def smoke_anchor(historical_cache: HistoricalDataCache) -> pd.Timestamp:
    anchor = select_backtesting_smoke_anchor(
        historical_cache,
        prefer_date=SMOKE_DAY,
        max_eauto_kwh=DEFAULT_MAX_EAUTO_KWH,
    )
    return pd.Timestamp(anchor)


@pytest.fixture(scope="module")
def smoke_prices_df(smoke_anchor: pd.Timestamp) -> pd.DataFrame:
    sim_cfg = config.get_file_paths_battery_simulation()
    start = smoke_anchor.normalize() - pd.Timedelta(days=1)
    end = smoke_anchor.normalize() + pd.Timedelta(days=2)
    return load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )


@pytest.fixture(scope="module")
def runtime_scenario_params() -> dict:
    scenarios = config.get_backtesting_scenarios()
    if "runtime_settings" not in scenarios:
        pytest.fail("config: backtesting_scenarios.runtime_settings fehlt")
    return dict(scenarios["runtime_settings"])


@requires_historical_data
def test_smoke_anchor_has_no_eauto_load(historical_cache: HistoricalDataCache):
    anchor = select_backtesting_smoke_anchor(
        historical_cache,
        prefer_date=SMOKE_DAY,
        max_eauto_kwh=DEFAULT_MAX_EAUTO_KWH,
    )
    from simulation.engine import window_slot_datetimes

    _, totals, _ = historical_cache.get_window_consumption(window_slot_datetimes(anchor))
    assert totals.get("eauto", 0.0) <= DEFAULT_MAX_EAUTO_KWH


@requires_historical_data
def test_historical_charging_context_keeps_time_window(
    historical_cache: HistoricalDataCache,
    smoke_anchor: pd.Timestamp,
    smoke_prices_df: pd.DataFrame,
):
    from simulation.engine import build_historical_window_matrix

    matrix, meta = build_historical_window_matrix(
        smoke_anchor.to_pydatetime(),
        historical_cache,
        smoke_prices_df,
    )
    eauto = next(
        c
        for c in config.get_flexible_consumers(optimizer_only=True)
        if c["id"] == "eauto"
    )
    ctx = resolve_charging_context(
        eauto,
        matrix,
        meta["consumer_daily_targets_kwh"],
        logged_simulation=True,
    )
    assert ctx.get("use_time_window") is True


@requires_historical_data
def test_logged_day_milp_skips_urgent_deadline_constraint(
    historical_cache: HistoricalDataCache,
    smoke_anchor: pd.Timestamp,
    smoke_prices_df: pd.DataFrame,
    runtime_scenario_params: dict,
):
    from simulation.engine import build_historical_window_matrix, _scenario_to_battery_params

    matrix, meta = build_historical_window_matrix(
        smoke_anchor.to_pydatetime(),
        historical_cache,
        smoke_prices_df,
        feed_in_settings=config.get_feed_in_settings(
            runtime_override=runtime_scenario_params
        ),
    )
    captured: list[bool] = []
    from optimizer import milp as milp_module

    original = milp_module._add_consumer_delivery_constraints

    def _capture_and_call(*args, **kwargs):
        captured.append(kwargs.get("include_urgent_deadline_constraint", True))
        return original(*args, **kwargs)

    battery = _scenario_to_battery_params(runtime_scenario_params)
    with patch.object(
        milp_module,
        "_add_consumer_delivery_constraints",
        side_effect=_capture_and_call,
    ):
        milp_optimizer(
            matrix,
            matrix[0]["hour"],
            50.0,
            battery_params=battery,
            verbose=False,
            consumer_remaining_kwh=meta["consumer_daily_targets_kwh"],
            flex_indices=list(range(len(matrix))),
            charging_contexts=None,
        )
    assert captured == [False]


@requires_historical_data
def test_backtesting_run_simulation_single_window(
    historical_cache: HistoricalDataCache,
    smoke_anchor: pd.Timestamp,
    smoke_prices_df: pd.DataFrame,
    runtime_scenario_params: dict,
):
    day = smoke_anchor.normalize()
    df, plausibility = run_simulation(
        day,
        day,
        runtime_scenario_params,
        smoke_prices_df,
        cache=historical_cache,
    )
    assert len(df) == 24
    assert plausibility.failed == []
    assert df["sim_cost"].notna().all()


@requires_historical_data
def test_backtesting_reference_costs_single_window(
    historical_cache: HistoricalDataCache,
    smoke_anchor: pd.Timestamp,
    smoke_prices_df: pd.DataFrame,
    runtime_scenario_params: dict,
):
    day = smoke_anchor.normalize()
    ref_settings = config.get_feed_in_settings(runtime_override=runtime_scenario_params)
    df = compute_historical_reference_costs(
        day,
        day,
        smoke_prices_df,
        ref_settings,
        cache=historical_cache,
    )
    assert len(df) == 24
    assert df["sim_cost"].notna().all()


@requires_historical_data
def test_backtesting_log_roundtrip(tmp_path, smoke_anchor: pd.Timestamp):
    ts = pd.date_range(
        smoke_anchor - pd.Timedelta(hours=23),
        periods=24,
        freq="h",
    )
    sample = pd.DataFrame(
        {
            "sim_cost": [0.01] * 24,
            "sim_soc": [50.0] * 24,
            "batt_action_kw": [0.0] * 24,
            "steuerbefehl": ["Automatik"] * 24,
        },
        index=ts,
    )
    sample.index.name = "ts"
    results = {HISTORICAL_REFERENCE_ID: sample, "runtime_settings": sample}
    labels = {
        HISTORICAL_REFERENCE_ID: "Historisch (ohne Optimierung)",
        "runtime_settings": "Runtime (Baseline)",
    }
    plausibility = {
        "runtime_settings": PlausibilityReport(),
    }
    period_meta = {
        "start": ts[0].date().isoformat(),
        "end": ts[-1].date().isoformat(),
        "windows": 1,
    }
    log_path = save_backtesting_log(
        results,
        labels,
        plausibility,
        period_meta,
        log_dir=str(tmp_path),
    )
    assert os.path.isfile(log_path)
    meta, hourly = load_backtesting_log(str(tmp_path))
    assert meta["period"]["windows"] == 1
    assert len(hourly) == 48
