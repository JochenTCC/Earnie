"""Cost and savings helpers for horizon simulation outputs."""
from __future__ import annotations

import config
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h
from optimizer.sim_chart_rows import flexible_consumer_power_kw, resolve_sell_price_cent
from optimizer.targets import consumer_column_name


def total_consumption_kwh_from_rows(
    rows: list,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> float:
    """Sum consumption energy (baseload + flex) over simulation slots."""
    dt_h = validate_dt_h(dt_h)
    return round(
        sum(
            (
                float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
                + flexible_consumer_power_kw(row)
            )
            * dt_h
            for row in rows
        ),
        3,
    )


def delivered_flex_kwh_from_rows(
    rows: list,
    *,
    flexible_consumers: list | None = None,
    dt_h: float = DEFAULT_DT_H,
) -> dict[str, float]:
    """Summiert die gelieferte Flex-Energie je Verbraucher über alle Simulationsslots."""
    dt_h = validate_dt_h(dt_h)
    totals: dict[str, float] = {}
    consumers_cfg = flexible_consumers or config.get_flexible_consumers(
        optimizer_only=True
    )
    for consumer in consumers_cfg:
        col = consumer_column_name(consumer)
        totals[consumer["id"]] = round(
            sum(float(row.get(col, 0.0) or 0.0) * dt_h for row in rows),
            3,
        )
    return totals


def _grid_kw_from_row(row: dict) -> float:
    """Netzbezug (kW): positiv = Bezug, negativ = Einspeisung."""
    if "Netzbezug (kW)" in row:
        return float(row["Netzbezug (kW)"])
    p_con = row["Verbrauch-Prognose (kW)"] + flexible_consumer_power_kw(row)
    p_pv = row["PV-Prognose (kW)"]
    batt_action = row["Geplante Batterie-Aktion (kW)"]
    return float(p_con - p_pv + batt_action)


def calculate_step_cost_parts_from_row(
    row: dict,
    sell_price_cent: float | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> tuple[float, float, float, float, float]:
    """Import/export split for one sim slot.

    Returns ``(import_cost_eur, export_earn_eur, net_eur, import_kwh, export_kwh)``.
    ``export_earn_eur`` and ``export_kwh`` are non-negative; ``net_eur = import − export``.
    """
    dt_h = validate_dt_h(dt_h)
    price_cent = row["Strompreis (Cent/kWh)"]
    sell_cent = resolve_sell_price_cent(row, sell_price_cent)
    p_grid = _grid_kw_from_row(row)
    if p_grid >= 0:
        import_kwh = float(p_grid) * dt_h
        import_eur = import_kwh * float(price_cent) / 100.0
        return import_eur, 0.0, import_eur, import_kwh, 0.0
    export_kwh = float(-p_grid) * dt_h
    export_eur = export_kwh * float(sell_cent) / 100.0
    return 0.0, export_eur, -export_eur, 0.0, export_kwh


def calculate_step_cost_euro_from_row(
    row: dict,
    sell_price_cent: float | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> float:
    """Berechnet die Stromkosten eines einzelnen Simulationsslots in Euro."""
    return calculate_step_cost_parts_from_row(
        row, sell_price_cent, dt_h=dt_h
    )[2]


def calculate_cost_euro_from_rows(
    rows: list,
    sell_price_cent: float | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> float:
    """Berechnet die Kosten in Euro für eine Slot-Reihe aus einem Simulations-Output."""
    return sum(
        calculate_step_cost_euro_from_row(row, sell_price_cent, dt_h=dt_h)
        for row in rows
    )


def hourly_consumption_kwh_from_rows(
    rows: list,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> list[float]:
    """Gesamtverbrauch (Grundlast + Flex) in kWh je Simulationszeile."""
    dt_h = validate_dt_h(dt_h)
    return [
        round(
            (
                float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
                + flexible_consumer_power_kw(row)
            )
            * dt_h,
            4,
        )
        for row in rows
    ]


def hourly_cost_euro_from_rows(rows: list, sell_price_cent: float | None = None) -> list[float]:
    """Stündliche Stromkosten in Euro je Simulationszeile."""
    return [
        round(calculate_step_cost_euro_from_row(row, sell_price_cent), 4)
        for row in rows
    ]


def hourly_savings_euro_from_rows(
    matched_baseline_rows: list,
    optimized_rows: list,
    sell_price_cent: float | None = None,
) -> list[float]:
    """
    Stündliche Einsparung vs. Ziel-Baseline (positiv = günstiger optimiert).
    Summe entspricht savings_matched_euro in calculate_optimization_savings.
    """
    matched = hourly_cost_euro_from_rows(matched_baseline_rows, sell_price_cent)
    optimized = hourly_cost_euro_from_rows(optimized_rows, sell_price_cent)
    hour_count = min(len(matched), len(optimized))
    return [round(matched[i] - optimized[i], 4) for i in range(hour_count)]


def _round_savings_list(values: list | None, *, digits: int = 4) -> list[float]:
    return [round(float(value), digits) for value in (values or [])]


def build_savings_snapshot(savings_info: dict) -> dict:
    """Kompakte Einsparungs-Kennzahlen für optimization_history (ohne Simulationszeilen)."""
    required = (
        "baseline_cost_euro",
        "matched_baseline_cost_euro",
        "optimized_cost_euro",
        "savings_euro",
        "savings_matched_euro",
    )
    for key in required:
        if key not in savings_info:
            raise ValueError(f"savings_info fehlt Feld {key!r}")

    return {
        "baseline_cost_euro": round(float(savings_info["baseline_cost_euro"]), 4),
        "matched_baseline_cost_euro": round(
            float(savings_info["matched_baseline_cost_euro"]), 4
        ),
        "optimized_cost_euro": round(float(savings_info["optimized_cost_euro"]), 4),
        "savings_euro": round(float(savings_info["savings_euro"]), 4),
        "savings_matched_euro": round(float(savings_info["savings_matched_euro"]), 4),
        "hourly_savings_euro": _round_savings_list(
            savings_info.get("hourly_savings_euro")
        ),
        "hourly_matched_baseline_cost_euro": _round_savings_list(
            savings_info.get("hourly_matched_baseline_cost_euro")
        ),
        "hourly_optimized_cost_euro": _round_savings_list(
            savings_info.get("hourly_optimized_cost_euro")
        ),
    }


def calculate_optimization_savings(
    optimization_matrix: list,
    initial_soc: float,
    consumer_daily_targets_kwh: dict[str, float] | None = None,
    sunrise_soc_min_index: int | None = None,
    filter_contexts: dict[str, dict] | None = None,
) -> dict:
    """Berechnet die Einsparung in Euro gegenüber einer nicht-optimierten Baseline-Simulation.

    Optimized path uses open-loop ``commit_hours=len(matrix)`` (one MILP), not
    per-slot MPC — Live control already solved once; savings/charts must stay fast
    on QH horizons (~188 slots).
    """
    from optimizer.charge_immediate import prepare_optimization_matrix
    from optimizer.charging_context import (
        apply_horizon_charging_limits,
        serialize_charging_contexts,
    )
    from optimizer.filter_context import resolve_filter_contexts
    from optimizer.sim_baseline import (
        simulate_baseline_horizon,
        simulate_baseline_with_optimized_flex,
        simulate_matched_baseline_horizon,
    )
    from optimizer.simulation import simulate_horizon
    from optimizer.targets import (
        build_applied_targets_detail,
        build_baseline_targets_detail,
        build_energy_comparison_detail,
        resolve_baseload_kwh,
        resolve_horizon_consumer_targets_kwh,
        resolve_matched_baseline_horizon_targets,
    )

    matrix, charging_contexts, targets = prepare_optimization_matrix(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )
    filters = filter_contexts or resolve_filter_contexts(matrix)
    # Open-loop: one CBC solve for the display horizon (not commit_hours=1 MPC).
    optimized_rows = simulate_horizon(
        matrix,
        initial_soc,
        consumer_daily_targets_kwh=targets,
        verbose=False,
        charging_contexts=charging_contexts,
        filter_contexts=filters,
        matrix_prepared=True,
        sunrise_soc_min_index=sunrise_soc_min_index,
        commit_hours=len(matrix),
    )
    baseline_rows = simulate_baseline_horizon(
        matrix, initial_soc, charging_contexts=charging_contexts
    )
    horizon_targets = resolve_horizon_consumer_targets_kwh(
        matrix,
        targets,
    )
    horizon_targets = apply_horizon_charging_limits(horizon_targets, charging_contexts)
    matched_targets = resolve_matched_baseline_horizon_targets(
        matrix,
        targets,
        charging_contexts,
    )
    matched_baseline_rows = simulate_matched_baseline_horizon(
        matrix,
        initial_soc,
        matched_targets,
        charging_contexts,
    )
    sell_price_cent = None
    optimized_cost = calculate_cost_euro_from_rows(optimized_rows, sell_price_cent)
    baseline_cost = calculate_cost_euro_from_rows(baseline_rows, sell_price_cent)
    matched_baseline_cost = calculate_cost_euro_from_rows(
        matched_baseline_rows, sell_price_cent
    )
    savings = baseline_cost - optimized_cost
    savings_matched_euro = matched_baseline_cost - optimized_cost
    baseline_kwh = total_consumption_kwh_from_rows(baseline_rows)
    matched_baseline_kwh = total_consumption_kwh_from_rows(matched_baseline_rows)
    optimized_kwh = total_consumption_kwh_from_rows(optimized_rows)
    applied_targets = build_applied_targets_detail(
        matrix,
        targets,
    )
    baseline_targets = build_baseline_targets_detail(matrix)
    matched_flex_kwh = (
        delivered_flex_kwh_from_rows(matched_baseline_rows)
        if matched_baseline_rows
        else None
    )
    energy_comparison = build_energy_comparison_detail(
        matrix,
        targets,
        matched_flex_kwh=matched_flex_kwh,
    )
    baseline_same_flex_rows = simulate_baseline_with_optimized_flex(
        matrix,
        optimized_rows,
        initial_soc,
    )
    hourly_matched_cost = hourly_cost_euro_from_rows(
        matched_baseline_rows, sell_price_cent
    )
    hourly_optimized_cost = hourly_cost_euro_from_rows(optimized_rows, sell_price_cent)
    hourly_savings = hourly_savings_euro_from_rows(
        matched_baseline_rows, optimized_rows, sell_price_cent
    )
    hourly_battery_only_cost = hourly_cost_euro_from_rows(
        baseline_same_flex_rows, sell_price_cent
    )
    hourly_matched_consumption = hourly_consumption_kwh_from_rows(matched_baseline_rows)
    hourly_optimized_consumption = hourly_consumption_kwh_from_rows(optimized_rows)
    return {
        "baseline_cost_euro": round(baseline_cost, 4),
        "matched_baseline_cost_euro": round(matched_baseline_cost, 4),
        "optimized_cost_euro": round(optimized_cost, 4),
        "savings_euro": round(savings, 4),
        "savings_matched_euro": round(savings_matched_euro, 4),
        "baseline_consumption_kwh": round(baseline_kwh, 3),
        "matched_baseline_consumption_kwh": round(matched_baseline_kwh, 3),
        "optimized_consumption_kwh": round(optimized_kwh, 3),
        "baseload_kwh": resolve_baseload_kwh(matrix),
        "baseline_targets": baseline_targets,
        "applied_targets": applied_targets,
        "energy_comparison": energy_comparison,
        "charging_contexts": serialize_charging_contexts(charging_contexts),
        "optimized_rows": optimized_rows,
        "baseline_rows": baseline_rows,
        "matched_baseline_rows": matched_baseline_rows,
        "baseline_same_flex_rows": baseline_same_flex_rows,
        "hourly_matched_baseline_cost_euro": hourly_matched_cost,
        "hourly_optimized_cost_euro": hourly_optimized_cost,
        "hourly_battery_only_baseline_cost_euro": hourly_battery_only_cost,
        "hourly_savings_euro": hourly_savings,
        "hourly_matched_baseline_consumption_kwh": hourly_matched_consumption,
        "hourly_optimized_consumption_kwh": hourly_optimized_consumption,
    }
