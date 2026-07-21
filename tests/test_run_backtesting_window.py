"""Unit-Tests für resolve_backtesting_window und SoC-Kette über zwei Fenster."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from optimizer import battery as bat
from scripts.run_backtesting import (
    _parse_month,
    resolve_backtesting_window,
)
from simulation.engine import (
    _scenario_to_battery_params,
    list_simulation_anchors,
    run_simulation,
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


def _horizon_end_soc_from_hourly(
    df: pd.DataFrame,
    start_soc: float,
    battery_params: dict,
) -> float:
  soc = float(start_soc)
  for _, row in df.iterrows():
      soc = float(row["sim_soc"])
      batt = float(row["batt_action_kw"] or 0.0)
      soc, _ = bat.apply_soc_change(
          soc,
          batt,
          battery_params["battery_capacity_kwh"],
          battery_params["efficiency"],
          battery_params["min_soc"],
          battery_params["max_soc"],
      )
  return round(soc, 1)


class TestParseMonth:
    def test_parses_valid_month(self, monkeypatch):
        from datetime import date

        monkeypatch.setattr(
            "data.profile_manager.get_cons_data_date_bounds",
            lambda: (date(2026, 1, 1), date(2026, 6, 25)),
        )
        ts = _parse_month("6")
        assert ts == pd.Timestamp(2026, 6, 1)

    def test_rejects_invalid_month(self):
        import argparse

        with pytest.raises(argparse.ArgumentTypeError, match="zwischen 1 und 12"):
            _parse_month("13")


class TestResolveBacktestingWindow:
    @pytest.fixture(autouse=True)
    def _fixtures(self, monkeypatch):
        with activate_backtesting_fixtures(monkeypatch):
            yield

    def test_month_range_within_fixture_bounds(self):
        start = _parse_month("6")
        end = _parse_month("6")
        # Fixture-Daten reichen bis 2026-06-25; Juni 2025 liegt dazwischen ohne Logs,
        # aber die Datumsauflösung selbst muss ein gültiges Intervall liefern.
        resolved_start, resolved_end = resolve_backtesting_window(
            start,
            end,
            "last_12_months",
        )
        assert resolved_start.month == 6
        assert resolved_end.month == 6
        assert resolved_start.year == 2026
        assert resolved_start <= resolved_end

    def test_june_2026_clamped_to_fixture_data(self, monkeypatch):
        """Juni 2026: Enddatum wird auf letzten Log-Tag (2026-06-25) begrenzt."""
        monkeypatch.setattr(
            "scripts.run_backtesting.pd.Timestamp.now",
            lambda: pd.Timestamp("2026-07-03"),
        )
        start = pd.Timestamp(2026, 6, 1)
        end = pd.Timestamp(2026, 6, 1)
        resolved_start, resolved_end = resolve_backtesting_window(
            start,
            end,
            "last_12_months",
        )
        assert resolved_start == pd.Timestamp("2026-06-01")
        assert resolved_end == pd.Timestamp("2026-06-25")

    def test_requires_both_months(self):
        start = _parse_month("6")
        with pytest.raises(SystemExit, match="gemeinsam"):
            resolve_backtesting_window(
                start,
                None,
                "last_12_months",
            )

    def test_rejects_start_after_end_month(self):
        start = _parse_month("8")
        end = _parse_month("6")
        with pytest.raises(SystemExit, match="darf nicht nach"):
            resolve_backtesting_window(
                start,
                end,
                "last_12_months",
            )


class TestSocChainTwoWindows:
    @pytest.fixture(autouse=True)
    def _fixtures(self, monkeypatch):
        with activate_backtesting_fixtures(monkeypatch):
            yield

    def test_two_day_run_has_continuous_soc(self):
        cache = load_fixture_cache()
        scenario = fixture_scenario_params()
        prices = build_synthetic_prices_df(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
        )
        start = pd.Timestamp(SOC_CHAIN_START_DAY)
        end = pd.Timestamp(SOC_CHAIN_END_DAY)
        anchors = list_simulation_anchors(start, end, cache)
        assert len(anchors) == 2, f"Erwartet 2 Fenster, erhalten: {anchors}"

        df, plausibility, _ = run_simulation(
            start,
            end,
            scenario,
            prices,
            cache=cache,
            initial_soc=50.0,
        )
        assert len(df) == 48
        assert plausibility.failed == []
        assert df["sim_soc"].notna().all()

        boundary_idx = 23
        battery_params = _scenario_to_battery_params(scenario)
        end_window_1 = _horizon_end_soc_from_hourly(
            df.iloc[:24],
            50.0,
            battery_params,
        )
        assert df["sim_soc"].iloc[boundary_idx + 1] == pytest.approx(
            end_window_1,
            abs=0.5,
        ), "SoC am Fensteranfang muss End-SOC der Vorstunde entsprechen"

        assert df["sim_soc"].iloc[0] == pytest.approx(50.0, abs=15.0)
        assert not all(df["sim_soc"] == pytest.approx(50.0, abs=0.01)), (
            "SoC sollte sich über zwei Fenster hinweg verändern"
        )
