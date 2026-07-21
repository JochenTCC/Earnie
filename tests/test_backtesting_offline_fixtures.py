"""Offline-Fixtures: Backtesting ohne lokale cons_data_hourly.csv."""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import pytest

from simulation.backtesting_log import load_backtesting_log, save_backtesting_log
from simulation.engine import (
    HISTORICAL_REFERENCE_ID,
    PlausibilityReport,
    compute_historical_reference_costs,
    list_simulation_anchors,
    run_simulation,
    window_anchor_for_date,
    window_slot_datetimes,
)
from tests.fixtures.backtesting_fixtures import (
    FIXTURES_ROOT,
    LOW_EAUTO_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")


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
    return fixture_scenario_params()


@pytest.fixture
def fixture_prices_df() -> pd.DataFrame:
    return build_synthetic_prices_df(
        pd.Timestamp("2024-07-01"),
        pd.Timestamp("2026-06-26"),
    )


def test_fixture_files_exist():
    assert (FIXTURES_ROOT / "config.json").is_file()
    assert (FIXTURES_ROOT / "backtesting_scenarios.json").is_file()
    assert (FIXTURES_ROOT / "cons_data_hourly.csv").is_file()


def test_fixture_config_loads_without_production_cons_data(
    backtesting_fixtures,
    monkeypatch,
):
    import config

    del backtesting_fixtures
    monkeypatch.chdir(FIXTURES_ROOT.parents[2])
    sim_cfg = config.get_scenario_explorer_conf()
    assert sim_cfg["path_cons_data"] == "tests/fixtures/backtesting/cons_data_hourly.csv"
    cache = load_fixture_cache()
    assert cache._consumption_df is not None
    assert not cache._consumption_df.empty


def test_fixture_has_expected_anchor_days(fixture_cache):
    anchors_low = list_simulation_anchors(
        pd.Timestamp(LOW_EAUTO_DAY),
        pd.Timestamp(LOW_EAUTO_DAY),
        fixture_cache,
    )
    assert anchors_low, "LOW_EAUTO_DAY sollte einen Simulationsanker liefern"
    anchor = anchors_low[0]
    _, totals, _, _ = fixture_cache.get_window_consumption(window_slot_datetimes(anchor))
    assert totals.get("eauto", 0.0) <= 0.05


def test_run_simulation_single_window_on_fixture(
    fixture_cache,
    fixture_scenario,
    fixture_prices_df,
):
    day = pd.Timestamp(LOW_EAUTO_DAY)
    df, plausibility, cbc_events = run_simulation(
        day,
        day,
        fixture_scenario,
        fixture_prices_df,
        cache=fixture_cache,
        scenario_id="fixture_5kwh_fixed",
    )
    assert len(df) == 24
    assert plausibility.failed == []
    assert df["sim_cost"].notna().all()
    assert isinstance(cbc_events, list)


def test_reference_costs_on_fixture(
    fixture_cache,
    fixture_scenario,
    fixture_prices_df,
    backtesting_fixtures,
):
    import config

    del backtesting_fixtures
    day = pd.Timestamp(LOW_EAUTO_DAY)
    ref_settings = config.get_backtesting_feed_in_settings(runtime_override=fixture_scenario)
    df = compute_historical_reference_costs(
        day,
        day,
        fixture_prices_df,
        ref_settings,
        cache=fixture_cache,
    )
    assert len(df) == 24
    assert df["sim_cost"].notna().all()


def test_backtesting_log_roundtrip_on_fixture(tmp_path, fixture_cache):
    anchor = window_anchor_for_date(LOW_EAUTO_DAY)
    ts = pd.date_range(
        pd.Timestamp(anchor) - pd.Timedelta(hours=23),
        periods=24,
        freq="h",
    )
    sample = pd.DataFrame(
        {
            "sim_cost": [0.02] * 24,
            "sim_soc": [55.0] * 24,
            "batt_action_kw": [0.0] * 24,
            "steuerbefehl": ["Automatik"] * 24,
        },
        index=ts,
    )
    sample.index.name = "ts"
    results = {HISTORICAL_REFERENCE_ID: sample, "fixture_5kwh_fixed": sample}
    labels = {
        HISTORICAL_REFERENCE_ID: "Historisch",
        "fixture_5kwh_fixed": "Fixture",
    }
    plausibility = {"fixture_5kwh_fixed": PlausibilityReport()}
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
    meta, hourly = load_backtesting_log(str(tmp_path))
    assert meta["period"]["windows"] == 1
    assert len(hourly) == 48
    assert log_path.endswith("backtesting_log.json")
