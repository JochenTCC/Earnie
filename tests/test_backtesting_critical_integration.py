"""Integrationstests für kritische Backtesting-Fenster (E-Auto, Grundlast-Kante)."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from simulation.baseload_validation import resolve_hourly_baseload_kw
from simulation.engine import (
    build_historical_window_matrix,
    run_simulation,
    validate_window_consumption,
    window_anchor_for_date,
    window_slot_datetimes,
)
from tests.fixtures.backtesting_fixtures import (
    BASELOAD_EDGE_DAY,
    HIGH_EAUTO_DAY,
    LOW_EAUTO_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _fixtures(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch):
        yield


@pytest.fixture
def fixture_cache():
    return load_fixture_cache()


@pytest.fixture
def fixture_scenario():
    return fixture_scenario_params()


@pytest.fixture
def wide_prices_df() -> pd.DataFrame:
    return build_synthetic_prices_df(
        pd.Timestamp("2024-07-01"),
        pd.Timestamp("2026-06-26"),
        base_cent=10.0,
        peak_cent=35.0,
    )


def test_critical_high_eauto_window_completes(
    fixture_cache,
    fixture_scenario,
    wide_prices_df,
):
    """E-Auto-lastiger Tag: MILP muss durchlaufen (kein Hänger)."""
    day = pd.Timestamp(HIGH_EAUTO_DAY)
    anchor = window_anchor_for_date(HIGH_EAUTO_DAY)
    _, totals, _, _ = fixture_cache.get_window_consumption(
        window_slot_datetimes(anchor)
    )
    assert totals.get("eauto", 0.0) > 5.0, "Fixture-Tag soll signifikante E-Auto-Last haben"

    df, plausibility, cbc_events = run_simulation(
        day,
        day,
        fixture_scenario,
        wide_prices_df,
        cache=fixture_cache,
        scenario_id="fixture_5kwh_fixed",
    )
    # Sunrise book ~24h; SA₀→SA₁ foresight flex may add hours for EV delivery.
    assert 23 <= len(df) <= 48
    assert df["sim_cost"].notna().all()
    assert df["sim_soc"].between(0.0, 100.0).all()
    assert isinstance(cbc_events, list)
    # Plausibilität kann bei schweren E-Auto-Fenstern scheitern – Lauf selbst ist die Aussage.
    assert len(plausibility.results) == 1


def test_critical_baseload_flex_exceeds_total_stays_non_negative(
    fixture_cache,
    fixture_scenario,
    wide_prices_df,
):
    """Stunden mit Flex > Total: skalierte Grundlast bleibt >= 0, Simulation bricht nicht ab."""
    anchor = window_anchor_for_date(BASELOAD_EDGE_DAY)
    slots = window_slot_datetimes(anchor)
    _, _, total_load, hourly_flex = fixture_cache.get_window_consumption(slots)
    assert any(f > t + 0.01 for f, t in zip(hourly_flex, total_load)), (
        "Fixture-Tag soll mindestens eine Stunde mit Flex > Total enthalten"
    )

    hourly_baseload, baseload_sum = resolve_hourly_baseload_kw(total_load, hourly_flex)
    assert all(value >= 0.0 for value in hourly_baseload)
    assert baseload_sum == pytest.approx(sum(total_load) - sum(hourly_flex), abs=0.05)

    matrix, meta = build_historical_window_matrix(
        anchor,
        fixture_cache,
        wide_prices_df,
    )
    from optimizer import simulate_horizon
    from simulation.engine import _scenario_to_battery_params

    battery = _scenario_to_battery_params(fixture_scenario)
    rows = simulate_horizon(
        matrix,
        50.0,
        battery_params=battery,
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
    )
    result = validate_window_consumption(rows, meta)
    assert result.historical_baseload_kwh is not None
    assert result.optimized_baseload_kwh is not None


def test_critical_low_eauto_passes_plausibility(
    fixture_cache,
    fixture_scenario,
    wide_prices_df,
):
    """Referenz-Gegenpol: leichtes Fenster muss Plausibilität bestehen."""
    day = pd.Timestamp(LOW_EAUTO_DAY)
    _, plausibility, _ = run_simulation(
        day,
        day,
        fixture_scenario,
        wide_prices_df,
        cache=fixture_cache,
    )
    assert plausibility.failed == []
