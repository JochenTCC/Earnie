"""Tests für Profil- und Ziel-Baseline in der Simulation."""
from __future__ import annotations

from tests.conftest import requires_historical_data
from optimizer.simulation import (
    build_matched_flex_kw_per_hour,
    delivered_flex_kwh_from_rows,
    simulate_baseline_horizon,
    simulate_matched_baseline_horizon,
    total_consumption_kwh_from_rows,
)


def _sample_matrix() -> list[dict]:
    return [
        {
            "hour": h,
            "expected_p_pv": 1.0,
            "expected_p_act": 0.5,
            "k_act": 20.0,
            "expected_flex_kw": {
                "swimspa": 1.0 if h < 12 else 0.0,
                "eauto": 0.5,
                "waermepumpe": 0.0,
            },
        }
        for h in range(24)
    ]


def test_build_matched_flex_scales_to_target():
    matrix = _sample_matrix()
    targets = {"swimspa": 6.0, "eauto": 12.0, "waermepumpe": 0.0}
    per_hour = build_matched_flex_kw_per_hour(matrix, targets)

    assert len(per_hour) == 24
    swimspa_sum = sum(hour["swimspa"] for hour in per_hour)
    eauto_sum = sum(hour["eauto"] for hour in per_hour)
    assert abs(swimspa_sum - 6.0) < 0.01
    assert abs(eauto_sum - 12.0) < 0.01
    assert all(hour["swimspa"] == 0.0 for hour in per_hour[12:])


def test_matched_baseline_matches_optimized_consumption_total():
    matrix = _sample_matrix()
    targets = {"swimspa": 6.0, "eauto": 12.0, "waermepumpe": 0.0}
    profile_rows = simulate_baseline_horizon(matrix, initial_soc=50.0)
    matched_rows = simulate_matched_baseline_horizon(matrix, 50.0, targets)

    profile_kwh = total_consumption_kwh_from_rows(profile_rows)
    matched_kwh = total_consumption_kwh_from_rows(matched_rows)
    matched_flex = delivered_flex_kwh_from_rows(matched_rows)

    assert matched_kwh < profile_kwh
    assert abs(matched_flex["swimspa"] - 6.0) < 0.05
    assert abs(matched_flex["eauto"] - 12.0) < 0.05
    assert all(row["Steuerbefehl"] == "Baseline (Ziel)" for row in matched_rows)


def test_hourly_cost_lists_sum_to_totals():
    matrix = _sample_matrix()
    targets = {"swimspa": 6.0, "eauto": 12.0, "waermepumpe": 0.0}
    matched_rows = simulate_matched_baseline_horizon(matrix, 50.0, targets)
    optimized_rows = simulate_baseline_horizon(matrix, initial_soc=50.0)

    from optimizer.simulation import (
        calculate_cost_euro_from_rows,
        hourly_cost_euro_from_rows,
        hourly_savings_euro_from_rows,
    )

    sell = 3.5
    matched_hourly = hourly_cost_euro_from_rows(matched_rows, sell)
    optimized_hourly = hourly_cost_euro_from_rows(optimized_rows, sell)
    hourly = hourly_savings_euro_from_rows(matched_rows, optimized_rows, sell)

    assert len(matched_hourly) == len(optimized_hourly) == len(hourly)
    assert abs(sum(matched_hourly) - calculate_cost_euro_from_rows(matched_rows, sell)) < 0.001
    assert abs(sum(optimized_hourly) - calculate_cost_euro_from_rows(optimized_rows, sell)) < 0.001
    assert all(abs(m - o - s) < 1e-4 for m, o, s in zip(matched_hourly, optimized_hourly, hourly))


def test_hourly_savings_sum_matches_total():
    matrix = _sample_matrix()
    targets = {"swimspa": 6.0, "eauto": 12.0, "waermepumpe": 0.0}
    matched_rows = simulate_matched_baseline_horizon(matrix, 50.0, targets)
    profile_rows = simulate_baseline_horizon(matrix, initial_soc=50.0)

    from optimizer.simulation import hourly_savings_euro_from_rows, calculate_cost_euro_from_rows

    sell = 3.5
    hourly = hourly_savings_euro_from_rows(matched_rows, profile_rows, sell)
    matched_cost = calculate_cost_euro_from_rows(matched_rows, sell)
    profile_cost = calculate_cost_euro_from_rows(profile_rows, sell)
    assert abs(sum(hourly) - (matched_cost - profile_cost)) < 0.001


def test_hourly_costs_equal_when_same_flex_and_battery_at_min_soc():
    """Bei gleicher Last und leerer Batterie müssen Stundenkosten übereinstimmen."""
    from optimizer.simulation import (
        hourly_cost_euro_from_rows,
        simulate_baseline_with_optimized_flex,
    )

    matrix = [
        {
            "hour": h,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.5,
            "k_act": 25.0,
            "expected_flex_kw": {},
        }
        for h in range(24)
    ]
    optimized_rows = [
        {
            "Uhrzeit": f"{h:02d}:00",
            "Strompreis (Cent/kWh)": 25.0,
            "PV-Prognose (kW)": 0.0,
            "Verbrauch-Prognose (kW)": 0.5,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 0.5,
            "Simulierter SoC (%)": 10.0,
            "E-Auto (kW)": 0.0,
            "SwimSpa (kW)": 0.0,
            "Wärmepumpe (kW)": 0.0,
        }
        for h in range(24)
    ]
    baseline_rows = simulate_baseline_with_optimized_flex(matrix, optimized_rows, 10.0)
    sell = 3.5
    opt_costs = hourly_cost_euro_from_rows(optimized_rows, sell)
    bl_costs = hourly_cost_euro_from_rows(baseline_rows, sell)
    for h in range(24):
        assert abs(opt_costs[h] - bl_costs[h]) < 0.001, f"hour {h}"


@requires_historical_data
def test_matched_eauto_profile_shape_scaled_to_current_target():
    """E-Auto BL Ziel: Profilform skaliert auf Ziel-kWh, nicht gleichmäßig im Fenster."""
    from datetime import date, datetime

    from optimizer.charging_context import historical_charging_context

    matrix = [
        {
            "hour": h,
            "date": date(2025, 6, 17),
            "expected_p_pv": 0.0,
            "expected_p_act": 0.5,
            "k_act": 20.0,
            "expected_flex_kw": {"eauto": 3.5 if 20 <= h <= 22 else 0.0},
        }
        for h in range(24)
    ]
    target_kwh = 12.0
    eauto = next(c for c in __import__("config").get_flexible_consumers() if c["id"] == "eauto")
    horizon_start = datetime(2025, 6, 17, 19, 0)
    ctx = historical_charging_context(
        eauto,
        matrix,
        {"eauto": target_kwh},
        horizon_start,
        realtime=True,
    )
    per_hour = build_matched_flex_kw_per_hour(matrix, {"eauto": target_kwh}, {"eauto": ctx})

    profile_sum = 3.5 * 3
    expected_evening = 3.5 * (target_kwh / profile_sum)
    assert per_hour[2]["eauto"] == 0.0
    assert abs(per_hour[20]["eauto"] - expected_evening) < 0.01
    assert abs(sum(h["eauto"] for h in per_hour) - target_kwh) < 0.01
