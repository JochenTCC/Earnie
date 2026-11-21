"""Tests für on-demand Einzelfenster-Backtesting."""
from __future__ import annotations

import os
from datetime import datetime

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


def test_initial_soc_without_series_fails_loud():
    anchor = window_anchor_for_date(LOW_EAUTO_DAY)
    with pytest.raises(ValueError, match="SoC"):
        initial_soc_for_anchor(anchor, "missing", pd.DataFrame())


def test_initial_soc_before_the_first_booked_slot_is_the_run_start_soc():
    from simulation.backtesting_single_window import RUN_START_SOC

    anchor = window_anchor_for_date(LOW_EAUTO_DAY)
    slots = window_slot_datetimes(anchor)
    hourly_df = pd.DataFrame(
        {"ts": [slots[4]], "scenario_id": ["fixture_5kwh_fixed"], "sim_soc": [62.5]}
    )
    assert initial_soc_for_anchor(anchor, "fixture_5kwh_fixed", hourly_df) == RUN_START_SOC


def test_initial_soc_missing_inside_the_series_fails_loud():
    anchor = window_anchor_for_date(LOW_EAUTO_DAY)
    slots = window_slot_datetimes(anchor)
    hourly_df = pd.DataFrame(
        {
            "ts": [slots[0] - pd.Timedelta(hours=1), slots[1]],
            "scenario_id": ["fixture_5kwh_fixed"] * 2,
            "sim_soc": [40.0, 62.5],
        }
    )
    with pytest.raises(ValueError, match="ohne SoC"):
        initial_soc_for_anchor(anchor, "fixture_5kwh_fixed", hourly_df)


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
    from optimizer.slot_duration import slots_for_wall_hours

    assert len(snapshot["chart_rows_24h"]) == slots_for_wall_hours(24)
    assert len(snapshot["matrix_24h"]) == slots_for_wall_hours(24)


def test_cache_key_normalizes_anchor():
    key = cache_key_for_window("2025-01-02T07:00:00", "live", "fixed_24h")
    assert key == ("2025-01-02T07:00:00", "live", "fixed_24h")


def _hourly_prices(start: str, end: str) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="h", inclusive="left")
    return pd.DataFrame({"price_cent_kwh": range(len(index))}, index=index, dtype=float)


def test_prices_load_anchor_dates_not_period_start_year(monkeypatch):
    """A period 2025-11 … 2026-10 has backtesting_year 2025; a March-2026 window needs 2026 prices."""
    from simulation import backtesting_single_window as module

    calls: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def fake_load(start, end, sim_cfg, timeout=30, *, market_zone=None):
        del sim_cfg, timeout, market_zone
        calls.append((start, end))
        return _hourly_prices(str(start.date()), str((end + pd.Timedelta(days=1)).date()))

    monkeypatch.setattr(module, "load_market_prices", fake_load)
    monkeypatch.setattr(module.config, "get_scenario_explorer_conf", lambda: {})
    module._load_prices_for_anchor(datetime(2026, 3, 19, 7), market_zone="AT")
    assert calls == [(pd.Timestamp(2026, 3, 16), pd.Timestamp(2026, 3, 21))]


def test_prices_not_covering_window_fail_loud(monkeypatch):
    """No constant-price fallback: prices that miss the window raise instead of being filled."""
    from simulation import backtesting_single_window as module

    monkeypatch.setattr(
        module,
        "load_market_prices",
        lambda *args, **kwargs: _hourly_prices("2026-03-18", "2026-03-22"),
    )
    monkeypatch.setattr(module.config, "get_scenario_explorer_conf", lambda: {})
    with pytest.raises(ValueError, match="decken das Fenster"):
        module._load_prices_for_anchor(datetime(2026, 3, 19, 7), market_zone="AT")
