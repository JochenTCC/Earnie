"""Savings forecast: the window's own consumers everywhere, and standby counted once.

Three defects of the savings path (code review of ``optimizer/``, 2026-11-11):

* an explicitly empty consumer list was replaced by the configured consumers,
* ``calculate_optimization_savings`` gave ``consumers`` only to the optimized run, the
  baselines took the configured list,
* the "same flex" baseline added the battery standby to a consumption that already held it.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from optimizer import sim_costs
from optimizer.sim_baseline import simulate_baseline_with_optimized_flex
from optimizer.simulation import (
    delivered_flex_kwh_from_rows,
    simulate_baseline_horizon,
    simulate_horizon,
)
from optimizer.targets import (
    resolve_horizon_consumer_targets_kwh,
    resolve_matched_baseline_horizon_targets,
)

BATTERY = {
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
}

CONFIGURED_SPA = {
    "id": "swimspa",
    "name": "Swimspa",
    "nominal_power_kw": 2.0,
    "min_on_quarterhours": 1,
    "daily_target_kwh": 1.0,
    "daily_target_source": "config",
    "chart_color_index": 0,
}

SECOND_CAR = {
    "id": "zweitauto",
    "name": "Zweitauto",
    "type": "ev",
    "nominal_power_kw": 3.5,
    "min_power_kw": 1.4,
    "min_on_quarterhours": 1,
    "daily_target_kwh": 0.0,
    "daily_target_source": "config",
    "chart_color_index": 1,
}


@pytest.fixture(autouse=True)
def _configured_consumers(monkeypatch):
    """The live configuration knows the spa only."""
    monkeypatch.setattr(
        "config.get_flexible_consumers", lambda *_a, **_k: [dict(CONFIGURED_SPA)]
    )


def _matrix(slots: int = 8) -> list[dict]:
    day = datetime(2025, 6, 1)
    return [
        {
            "hour": 0,
            "date": day.date(),
            "slot_datetime": day.replace(minute=0) if t == 0 else day.replace(hour=t // 4, minute=15 * (t % 4)),
            "expected_p_pv": 0.0,
            "expected_p_act": 0.5,
            "k_act": 20.0 + t,
            "k_push_act": 5.0,
            "expected_flex_kw": {"zweitauto": 2.0 if t < 4 else 0.0, "swimspa": 1.0},
        }
        for t in range(slots)
    ]


# --- an empty consumer list means "no consumers" ---------------------------------------


def test_empty_consumer_list_is_not_replaced_by_the_configured_consumers():
    assert delivered_flex_kwh_from_rows([{"Swimspa (kW)": 2.0}], flexible_consumers=[]) == {}
    assert resolve_horizon_consumer_targets_kwh(_matrix(), None, flexible_consumers=[]) == {}


def test_horizon_simulation_without_consumers_plans_no_configured_consumer():
    matrix = _matrix(4)
    rows = simulate_horizon(
        matrix,
        50.0,
        battery_params=BATTERY,
        k_push=5.0,
        verbose=False,
        flexible_consumers=[],
        charging_contexts={},
        filter_contexts={},
        matrix_prepared=True,
        commit_hours=len(matrix),
    )
    assert len(rows) == len(matrix)
    assert all("Swimspa (kW)" not in row for row in rows)


# --- the baselines use the consumers given to the savings calculation -----------------


def test_matched_targets_take_the_profile_of_a_window_only_consumer():
    targets = resolve_matched_baseline_horizon_targets(
        _matrix(), {"zweitauto": 0.0}, consumers=[SECOND_CAR]
    )
    # 4 slots at 2 kW and 0.25 h; the configured spa is not part of this window
    assert targets == {"zweitauto": pytest.approx(2.0)}


def test_savings_baselines_use_the_given_consumers(monkeypatch):
    monkeypatch.setattr(
        "optimizer.simulation.simulate_horizon",
        lambda matrix, initial_soc, **kw: simulate_baseline_horizon(
            matrix, initial_soc, consumers=kw["flexible_consumers"]
        ),
    )

    car = {**SECOND_CAR, "daily_target_kwh": 1.5}
    rows = sim_costs._run_savings_horizons(
        _matrix(),
        60.0,
        60.0,
        None,
        {},
        {},
        sunrise_soc_min_index=None,
        consumers=[car],
    )

    for baseline in (rows.baseline, rows.matched_baseline, rows.matched_baseline_costed):
        assert all("Zweitauto (kW)" in row for row in baseline)
        assert all("Swimspa (kW)" not in row for row in baseline)
    delivered = delivered_flex_kwh_from_rows(
        rows.matched_baseline_costed, flexible_consumers=[car]
    )
    assert delivered["zweitauto"] == pytest.approx(1.5, abs=0.05)


# --- battery standby is counted once in the "same flex" baseline ------------------------


def test_same_flex_baseline_does_not_add_standby_twice():
    battery = {**BATTERY, "standby_power_kw": 0.1}
    matrix = _matrix(4)
    # the optimized chart row already holds load + standby
    optimized = [{"Swimspa (kW)": 0.0, "Verbrauch-Prognose (kW)": 0.6}] * len(matrix)

    rows = simulate_baseline_with_optimized_flex(
        matrix, optimized, 50.0, battery_params=battery
    )

    assert [row["Verbrauch-Prognose (kW)"] for row in rows] == pytest.approx([0.6] * 4)


def test_same_flex_baseline_adds_standby_to_the_matrix_load():
    battery = {**BATTERY, "standby_power_kw": 0.1}
    matrix = _matrix(4)
    # no consumption column: the matrix load (0.5 kW) plus standby
    optimized = [{"Swimspa (kW)": 0.0}] * len(matrix)

    rows = simulate_baseline_with_optimized_flex(
        matrix, optimized, 50.0, battery_params=battery
    )

    assert [row["Verbrauch-Prognose (kW)"] for row in rows] == pytest.approx([0.6] * 4)
