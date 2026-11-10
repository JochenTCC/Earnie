"""SE window view: the baselines use the window's own consumers, not the Live profile's.

A scenario on another house profile can have consumers Live does not know (multi-EV: a
second car). The baselines took the Live list, so the second car was missing from the
"same energy" baseline and the window showed Earnie more expensive than the baseline.
"""
from __future__ import annotations

from optimizer.simulation import (
    delivered_flex_kwh_from_rows,
    simulate_baseline_with_optimized_flex,
    simulate_matched_baseline_horizon,
)

SECOND_CAR = {
    "id": "zweitauto",
    "name": "Zweitauto",
    "type": "ev",
    "nominal_power_kw": 3.5,
    "min_power_kw": 1.4,
    "min_on_quarterhours": 1,
    "daily_target_kwh": 0.0,
    "daily_target_source": "config",
    "chart_color_index": 0,
}


def _matrix() -> list[dict]:
    return [
        {
            "hour": h,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.5,
            "k_act": 20.0,
            "expected_flex_kw": {"zweitauto": 2.0 if h < 4 else 0.0},
        }
        for h in range(8)
    ]


def test_matched_baseline_charges_a_scenario_only_car():
    rows = simulate_matched_baseline_horizon(
        _matrix(), 50.0, {"zweitauto": 2.0}, consumers=[SECOND_CAR]
    )
    delivered = delivered_flex_kwh_from_rows(rows, flexible_consumers=[SECOND_CAR])
    assert abs(delivered["zweitauto"] - 2.0) < 0.05
    assert "Zweitauto (kW)" in rows[0]


def test_same_flex_baseline_reads_the_scenario_only_car():
    optimized = [{"Zweitauto (kW)": 3.5, "Verbrauch-Prognose (kW)": 0.5}] * 8
    rows = simulate_baseline_with_optimized_flex(
        _matrix(), optimized, 50.0, consumers=[SECOND_CAR]
    )
    assert all(row["Zweitauto (kW)"] == 3.5 for row in rows)
