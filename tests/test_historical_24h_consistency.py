# tests/test_historical_24h_consistency.py
"""Konsistenz der 24h-Optimierung an historischen Loxone-Log-Tagen."""
from __future__ import annotations

import os

import pandas as pd
import pytest

import config
import data_loader
from optimization_consistency import assert_24h_optimization_consistent, validate_24h_optimization_run
from optimizer import simulate_horizon
from simulation_engine import (
    HistoricalDataCache,
    _scenario_to_battery_params,
    build_historical_window_matrix,
)
from tests.conftest import requires_historical_data
from tests.historical_case_selection import (
    HistoricalConsistencyCase,
    select_monthly_pv_extreme_cases,
)

# Offline: keine Loxone-API beim Import von config
os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

_CASES: list[HistoricalConsistencyCase] = []
_CASE_IDS: list[str] = []


def _load_cases() -> tuple[list[HistoricalConsistencyCase], list[str]]:
    if not (os.path.isfile("cons_data_hourly.csv") and os.path.isfile("config.json")):
        return [], []
    try:
        cases = select_monthly_pv_extreme_cases(months_back=12)
    except (ValueError, OSError, KeyError):
        return [], []
    return cases, [case.case_id for case in cases]


_CASES, _CASE_IDS = _load_cases()


@pytest.fixture(scope="module")
def historical_cache() -> HistoricalDataCache:
    cache = HistoricalDataCache()
    cache.load()
    return cache


@pytest.fixture(scope="module")
def prices_df(historical_cache: HistoricalDataCache) -> pd.DataFrame:
    del historical_cache
    sim_cfg = config.get_file_paths_battery_simulation()
    idx = pd.read_csv(
        "cons_data_hourly.csv",
        sep=";",
        usecols=["timestamp"],
        parse_dates=["timestamp"],
    )
    start = pd.Timestamp(idx["timestamp"].min()).normalize()
    end = pd.Timestamp(idx["timestamp"].max()).normalize() + pd.Timedelta(days=1)
    return data_loader.load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )


@pytest.fixture(scope="module")
def scenario_params() -> dict:
    return dict(config.CONFIG._raw_config["runtime_settings"])


@requires_historical_data
@pytest.mark.skipif(
    not _CASES,
    reason="Keine gültigen historischen 24h-Fenster in cons_data_hourly.csv",
)
@pytest.mark.parametrize("historical_case", _CASES, ids=_CASE_IDS)
def test_historical_24h_optimization_is_internally_consistent(
    historical_case: HistoricalConsistencyCase,
    historical_cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
):
    matrix, meta = build_historical_window_matrix(
        historical_case.anchor,
        historical_cache,
        prices_df,
    )
    battery_params = _scenario_to_battery_params(scenario_params)
    initial_soc = 50.0
    rows = simulate_horizon(
        matrix,
        initial_soc,
        battery_params=battery_params,
        k_push=float(scenario_params["k_push_cent"]),
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
    )
    report = validate_24h_optimization_run(
        matrix,
        rows,
        anchor=historical_case.anchor,
        initial_soc=initial_soc,
        battery_params=battery_params,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
        sell_price_cent=float(scenario_params["k_push_cent"]),
        label=historical_case.case_id,
    )
    assert_24h_optimization_consistent(report)


@requires_historical_data
def test_historical_case_catalog_has_expected_size():
    """Ca. 24 Läufe (2 PV-Extreme pro Monat über 12 Monate)."""
    cases = select_monthly_pv_extreme_cases(months_back=12)
    assert len(cases) >= 20, (
        f"Zu wenige historische Testfälle ({len(cases)}); "
        "cons_data_hourly.csv sollte mindestens 12 Monate abdecken."
    )
    labels = {case.label for case in cases}
    assert "high_pv" in labels
    assert "low_pv" in labels or "single_day" in labels
