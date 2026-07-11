# tests/test_historical_24h_consistency.py
"""Konsistenz der 24h-Optimierung an historischen Loxone-Log-Tagen."""
from __future__ import annotations

import os

import pandas as pd
import pytest

import config
from data import cons_data_store
from data.data_loader import load_market_prices
from optimizer.consistency import assert_24h_optimization_consistent, validate_24h_optimization_run
from optimizer import simulate_horizon
from simulation.engine import (
    HistoricalDataCache,
    _scenario_to_battery_params,
    build_historical_window_matrix,
)
from tests.conftest import requires_historical_data
from tests.fixtures.historical_fixtures import CONS_DATA_FILE, fixture_available
from tests.historical_case_selection import (
    HistoricalConsistencyCase,
    select_monthly_pv_extreme_cases,
)

# Offline: keine Loxone-API beim Import von config
os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")


def _load_cases() -> tuple[list[HistoricalConsistencyCase], list[str]]:
    if not fixture_available():
        return [], []
    try:
        cache = HistoricalDataCache(cons_data_path=str(CONS_DATA_FILE))
        cases = select_monthly_pv_extreme_cases(cache, months_back=12)
    except (ValueError, OSError, KeyError):
        return [], []
    return cases, [case.case_id for case in cases]


def pytest_generate_tests(metafunc):
    if "historical_case" not in metafunc.fixturenames:
        return
    cases, ids = _load_cases()
    if not cases:
        metafunc.parametrize(
            "historical_case",
            [
                pytest.param(
                    None,
                    marks=pytest.mark.skip(
                        reason="Keine gültigen historischen 24h-Fenster in der Test-Fixture"
                    ),
                )
            ],
        )
        return
    metafunc.parametrize("historical_case", cases, ids=ids)


@pytest.fixture(scope="module")
def historical_cache(historical_cons_data) -> HistoricalDataCache:
    cache = HistoricalDataCache(cons_data_path=historical_cons_data)
    cache.load()
    return cache


@pytest.fixture(scope="module")
def prices_df(historical_cons_data) -> pd.DataFrame:
    sim_cfg = config.get_file_paths_battery_simulation()
    idx = cons_data_store.load_cons_data(historical_cons_data)
    start = pd.Timestamp(idx.index.min()).normalize()
    end = pd.Timestamp(idx.index.max()).normalize() + pd.Timedelta(days=1)
    return load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )


@pytest.fixture(scope="module")
def scenario_params() -> dict:
    return dict(config.get_resolved_runtime_settings())


@requires_historical_data
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
        sell_price_cent=None,
        label=historical_case.case_id,
    )
    assert_24h_optimization_consistent(report)


@requires_historical_data
def test_historical_case_catalog_has_expected_size(historical_cons_data):
    """Ca. 24 Läufe (2 PV-Extreme pro Monat über 12 Monate)."""
    cache = HistoricalDataCache(cons_data_path=historical_cons_data)
    cases = select_monthly_pv_extreme_cases(cache, months_back=12)
    assert len(cases) >= 20, (
        f"Zu wenige historische Testfälle ({len(cases)}); "
        f"{CONS_DATA_FILE} sollte mindestens 12 Monate abdecken."
    )
    labels = {case.label for case in cases}
    assert "high_pv" in labels
    assert "low_pv" in labels or "single_day" in labels
