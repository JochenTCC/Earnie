"""sunrise_full_horizon_trial + flex_book_hours (2.3.c.3)."""
from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from data.feed_in_prices import FEED_IN_MODE_FIXED, FeedInSettings
from optimizer.simulation import _flex_indices_for_book_hours, simulate_horizon
from simulation.engine import (
    _simulate_anchor_step,
    build_sunrise_window_matrix,
    window_anchor_for_date,
)
from simulation.horizon_mode import BACKTESTING_STEP_HOURS, SUNRISE_WINDOW
from tests.fixtures.backtesting_fixtures import (
    SOC_CHAIN_END_DAY,
    SOC_CHAIN_START_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

_BATTERY = {
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
}


@pytest.fixture(autouse=True)
def _fixtures(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch):
        yield


def test_flex_indices_none_uses_full_remaining():
    assert _flex_indices_for_book_hours(40, 0, None) == list(range(40))
    assert _flex_indices_for_book_hours(30, 10, None) == list(range(30))


def test_flex_indices_clamps_to_absolute_book_window():
    assert _flex_indices_for_book_hours(40, 0, 24) == list(range(24))
    assert _flex_indices_for_book_hours(30, 20, 24) == list(range(4))
    assert _flex_indices_for_book_hours(20, 24, 24) == []
    assert _flex_indices_for_book_hours(10, 30, 24) == []


def _matrix(n: int = 40) -> list[dict]:
    from datetime import timedelta

    start = datetime(2025, 6, 1, 0, 0, 0)
    rows = []
    for h in range(n):
        slot = start + timedelta(hours=h)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "expected_p_pv": 0.5,
                "expected_p_act": 1.0,
                "k_act": 20.0,
                "k_push_act": 5.0,
            }
        )
    return rows


def test_simulate_horizon_passes_clamped_flex_indices():
    matrix = _matrix(40)
    schedule = [
        {
            "milp_plan": {
                "p_grid_buy": 0.0,
                "p_grid_sell": 0.0,
                "p_charge": 0.0,
                "p_discharge": 0.0,
            },
            "consumer_powers": {},
            "consumer_pv_follow": {},
            "planned_soc_percent": 50.0,
        }
        for _ in matrix
    ]
    with patch(
        "optimizer.simulation.milp_horizon_schedule",
        return_value=schedule,
    ) as mock_sched:
        with patch(
            "optimizer.simulation._apply_forced_grid_recharge_at_horizon_end",
            side_effect=lambda rows, soc, **kw: soc,
        ):
            rows = simulate_horizon(
                matrix,
                50.0,
                battery_params=_BATTERY,
                verbose=False,
                flexible_consumers=[],
                commit_hours=len(matrix),
                flex_book_hours=24,
                disable_horizon_soc_anchor=True,
            )
    assert len(rows) == 40
    assert mock_sched.call_count == 1
    assert mock_sched.call_args.kwargs["flex_indices"] == list(range(24))


def test_simulate_horizon_default_flex_indices_full_slice():
    matrix = _matrix(6)
    schedule = [
        {
            "milp_plan": {
                "p_grid_buy": 0.0,
                "p_grid_sell": 0.0,
                "p_charge": 0.0,
                "p_discharge": 0.0,
            },
            "consumer_powers": {},
            "consumer_pv_follow": {},
            "planned_soc_percent": 50.0,
        }
        for _ in matrix
    ]
    with patch(
        "optimizer.simulation.milp_horizon_schedule",
        return_value=schedule,
    ) as mock_sched:
        with patch(
            "optimizer.simulation._apply_forced_grid_recharge_at_horizon_end",
            side_effect=lambda rows, soc, **kw: soc,
        ):
            simulate_horizon(
                matrix,
                50.0,
                battery_params=_BATTERY,
                verbose=False,
                flexible_consumers=[],
                commit_hours=len(matrix),
                flex_book_hours=None,
            )
    assert mock_sched.call_args.kwargs["flex_indices"] == list(range(6))


def test_full_horizon_trial_passes_flex_book_hours(monkeypatch):
    scenario = fixture_scenario_params()
    cache = load_fixture_cache()
    prices = build_synthetic_prices_df(
        pd.Timestamp(SOC_CHAIN_START_DAY),
        pd.Timestamp(SOC_CHAIN_END_DAY),
    )
    anchor = window_anchor_for_date(SOC_CHAIN_START_DAY)
    _matrix, _meta, _idx, matrix_full = build_sunrise_window_matrix(
        anchor, cache, prices, scenario
    )
    assert len(matrix_full) > BACKTESTING_STEP_HOURS

    monkeypatch.setattr(
        "simulation.engine.config.get_backtesting_sunrise_full_horizon_trial",
        lambda: True,
    )
    monkeypatch.setattr(
        "simulation.engine.config.get_backtesting_disable_horizon_soc_anchor",
        lambda: False,
    )
    monkeypatch.setattr(
        "simulation.engine.config.get_backtesting_commit_hours",
        lambda: 24,
    )

    captured: dict = {}

    def _fake_simulate(matrix, sim_soc, **kwargs):
        captured["matrix_len"] = len(matrix)
        captured["flex_book_hours"] = kwargs.get("flex_book_hours")
        captured["disable"] = kwargs.get("disable_horizon_soc_anchor")
        captured["commit_hours"] = kwargs.get("commit_hours")
        rows = []
        for i, row in enumerate(matrix):
            rows.append(
                {
                    "slot_datetime": row["slot_datetime"],
                    "Simulierter SoC (%)": 50.0,
                    "Geplante Batterie-Aktion (kW)": 0.0,
                    "PV-Prognose (kW)": float(row.get("expected_p_pv", 0.0) or 0.0),
                    "Verbrauch-Prognose (kW)": float(
                        row.get("expected_p_act", 0.0) or 0.0
                    ),
                    "Netzbezug (kW)": 0.0,
                    "Steuerbefehl": "Automatikbetrieb",
                    "_horizon_end_soc": 50.0 if i == len(matrix) - 1 else None,
                }
            )
        return rows

    feed_in = FeedInSettings(
        mode=FEED_IN_MODE_FIXED,
        k_push_cent=5.0,
        fee_factor=0.0,
        fix_cent=5.0,
    )
    with patch("simulation.engine.simulate_horizon", side_effect=_fake_simulate):
        chart_rows, matrix_out, _meta2, new_soc, *_rest = _simulate_anchor_step(
            anchor,
            50.0,
            horizon_mode=SUNRISE_WINDOW,
            cache=cache,
            prices_df=prices,
            scenario_params=scenario,
            battery_params=_BATTERY,
            feed_in_settings=feed_in,
            hours_done=0,
            collect_cbc=False,
        )

    assert captured["matrix_len"] == len(matrix_full)
    assert captured["flex_book_hours"] == BACKTESTING_STEP_HOURS
    assert captured["disable"] is True
    assert captured["commit_hours"] == len(matrix_full)
    assert len(chart_rows) == BACKTESTING_STEP_HOURS
    assert len(matrix_out) == BACKTESTING_STEP_HOURS
    assert new_soc == pytest.approx(50.0)
