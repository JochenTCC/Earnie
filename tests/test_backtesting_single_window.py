"""Tests für on-demand Einzelfenster-Backtesting."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from simulation.backtesting_single_window import (
    cache_key_for_window,
    initial_soc_for_anchor,
    simulate_window_snapshot,
)
from simulation.engine import window_anchor_for_date, window_slot_datetimes
from tests.fixtures.backtesting_fixtures import (
    LOW_EAUTO_DAY,
    activate_backtesting_fixtures,
    load_fixture_cache,
)

os.environ.setdefault("EARNIE_OFFLINE", "1")


@pytest.fixture
def backtesting_fixtures(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch) as config_module:
        yield config_module


@pytest.fixture
def fixture_cache(backtesting_fixtures):
    del backtesting_fixtures
    return load_fixture_cache()


@pytest.fixture
def fixture_scenario(backtesting_fixtures):
    del backtesting_fixtures
    from tests.fixtures.backtesting_fixtures import fixture_scenario_params

    return fixture_scenario_params()


def test_initial_soc_from_hourly_df():
    anchor = window_anchor_for_date(LOW_EAUTO_DAY)
    slots = window_slot_datetimes(anchor)
    hourly_df = pd.DataFrame(
        {
            "ts": [slots[0]],
            "scenario_id": ["fixture_5kwh_fixed"],
            "sim_soc": [62.5],
        }
    )
    soc = initial_soc_for_anchor(anchor, "fixture_5kwh_fixed", hourly_df)
    assert soc == 62.5


def test_initial_soc_fallback_without_match():
    anchor = window_anchor_for_date(LOW_EAUTO_DAY)
    soc = initial_soc_for_anchor(anchor, "missing", pd.DataFrame())
    assert soc == 50.0


def test_simulate_window_snapshot_on_fixture(
    fixture_cache,
    fixture_scenario,
):
    anchor = window_anchor_for_date(LOW_EAUTO_DAY)
    meta = {
        "period": {
            "start": str(LOW_EAUTO_DAY),
            "end": str(LOW_EAUTO_DAY),
            "backtesting_year": LOW_EAUTO_DAY.year,
            "start_month": anchor.month,
            "end_month": anchor.month,
            "horizon_mode": "fixed_24h",
        },
    }
    snapshot = simulate_window_snapshot(
        anchor,
        "fixture_5kwh_fixed",
        meta,
        initial_soc=55.0,
        horizon_mode="fixed_24h",
        cache=fixture_cache,
    )
    assert snapshot["scenario_id"] == "fixture_5kwh_fixed"
    assert snapshot["kind"] == "on_demand"
    assert len(snapshot["chart_rows_24h"]) == 24
    assert len(snapshot["matrix_24h"]) == 24


def test_cache_key_normalizes_anchor():
    key = cache_key_for_window("2025-01-02T07:00:00", "live", "fixed_24h")
    assert key == ("2025-01-02T07:00:00", "live", "fixed_24h")
