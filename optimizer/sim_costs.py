"""Cost and savings helpers for horizon simulation outputs."""
from __future__ import annotations

from typing import NamedTuple

import config
from optimizer import battery as bat
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h
from optimizer.sim_chart_rows import (
    COL_BATTERIE_AKTION,
    COL_NETZBEZUG,
    COL_PV_PROGNOSE,
    COL_VERBRAUCH_PROGNOSE,
    flexible_consumer_power_kw,
    resolve_sell_price_cent,
)
from optimizer.targets import consumer_column_name

BASELINE_START_SHADOW_CHAIN = "shadow_chain"
BASELINE_START_LIVE_SOC = "live_soc"


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
                float(row.get(COL_VERBRAUCH_PROGNOSE, 0.0) or 0.0)
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
    consumers_cfg = (
        flexible_consumers
        if flexible_consumers is not None
        else config.get_flexible_consumers(optimizer_only=True)
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
    if COL_NETZBEZUG in row:
        return float(row[COL_NETZBEZUG])
    p_con = row[COL_VERBRAUCH_PROGNOSE] + flexible_consumer_power_kw(row)
    p_pv = row[COL_PV_PROGNOSE]
    batt_action = row[COL_BATTERIE_AKTION]
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
                float(row.get(COL_VERBRAUCH_PROGNOSE, 0.0) or 0.0)
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
    Summe entspricht savings_matched_euro in calculate_optimization_savings, solange
    Plan und Baseline vom selben SoC starten; sonst fehlt plan_soc_correction_euro.
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


class _SavingsRows(NamedTuple):
    """Simulationszeilen der Vergleichsläufe einer Einsparungsrechnung.

    ``matched_baseline`` carries the profile fallback (config consumers with target 0
    and profile energy) for the BL Ziel SoC and the ghost flex bars in Chart 1.
    ``matched_baseline_costed`` runs the same matched baseline on the optimizer's own
    targets only; BL Ziel € and kWh come from it, so the optimizer is never compared
    against energy it does not plan (savings-ledger D3). Without any fallback both
    are the same list.
    """

    optimized: list
    baseline: list
    matched_baseline: list
    matched_baseline_costed: list
    profile_fallback_kwh: dict[str, float]


def _profile_fallback_kwh(
    matched_targets: dict[str, float],
    costed_targets: dict[str, float],
) -> dict[str, float]:
    """Energy the matched baseline adds on top of the optimizer targets, per consumer."""
    fallback: dict[str, float] = {}
    for cid, matched_kwh in matched_targets.items():
        extra = float(matched_kwh or 0.0) - float(costed_targets.get(cid, 0.0) or 0.0)
        if extra > 0.0:
            fallback[cid] = round(extra, 3)
    return fallback


def _plan_p_ref_cent(rows: list) -> float:
    """Reference price of a plan as in the ledger (spec § 3): import-weighted, else the time mean."""
    parts = [calculate_step_cost_parts_from_row(row) for row in rows]
    import_kwh = sum(part[3] for part in parts)
    if import_kwh > 0.0:
        return sum(part[0] for part in parts) / import_kwh * 100.0
    return sum(float(row["Strompreis (Cent/kWh)"]) for row in rows) / len(rows)


def _soc_after_row(row: dict, battery_params: dict) -> float:
    soc_next, _ = bat.apply_soc_change(
        float(row["Simulierter SoC (%)"]),
        float(row["Geplante Batterie-Aktion (kW)"]),
        float(battery_params["battery_capacity_kwh"]),
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
        dt_h=DEFAULT_DT_H,
    )
    return soc_next


def soc_correction_increments_euro(
    optimized_rows: list,
    baseline_rows: list,
    battery_params: dict,
) -> list[float]:
    """Per-row change of the value of the SoC gap between plan and baseline (Ledger P11).

    Same formula as the ledger's day close (spec § 3): gap in % × capacity × efficiency
    × ``p_ref``. Their sum is the gap's value at the end minus its value at the start,
    the same telescoping as ``saving_adjusted``: the energy the plan holds over the
    baseline at the start is the ledger's correction already, so a plan that only uses
    that energy saves nothing. Summing up to a slot gives the correction of a window
    that ends there.
    """
    count = min(len(optimized_rows), len(baseline_rows))
    if count == 0:
        return []
    euro_per_percent = (
        float(battery_params["battery_capacity_kwh"])
        * float(battery_params["efficiency"])
        / 100.0
        * _plan_p_ref_cent(optimized_rows[:count])
        / 100.0
    )
    gaps = [
        float(optimized_rows[i]["Simulierter SoC (%)"]) - float(baseline_rows[i]["Simulierter SoC (%)"])
        for i in range(count)
    ]
    gaps.append(
        _soc_after_row(optimized_rows[count - 1], battery_params)
        - _soc_after_row(baseline_rows[count - 1], battery_params)
    )
    return [round((gaps[i + 1] - gaps[i]) * euro_per_percent, 4) for i in range(count)]


def _run_savings_horizons(
    matrix: list,
    initial_soc: float,
    baseline_soc: float,
    targets: dict[str, float] | None,
    charging_contexts: dict[str, dict] | None,
    filters: dict[str, dict] | None,
    *,
    sunrise_soc_min_index: int | None,
    consumers: list | None,
    current_soc_by_id: dict[str, float] | None = None,
) -> _SavingsRows:
    """Optimierter Open-Loop-Lauf plus freie und ziel-gematchte Baseline."""
    from optimizer.charging_context import apply_horizon_charging_limits
    from optimizer.sim_baseline import (
        simulate_baseline_horizon,
        simulate_matched_baseline_horizon,
    )
    from optimizer.simulation import simulate_horizon
    from optimizer.targets import (
        resolve_horizon_consumer_targets_kwh,
        resolve_matched_baseline_horizon_targets,
    )

    from runtime_store.cycle_timing import record_phase

    # Open-loop: one CBC solve for the display horizon (not commit_hours=1 MPC).
    with record_phase("savings_optimized"):
        optimized_rows = simulate_horizon(
            matrix,
            initial_soc,
            consumer_daily_targets_kwh=targets,
            verbose=False,
            charging_contexts=charging_contexts,
            filter_contexts=filters,
            matrix_prepared=True,
            sunrise_soc_min_index=sunrise_soc_min_index,
            flexible_consumers=consumers,
            commit_hours=len(matrix),
            current_soc_by_id=current_soc_by_id,
        )
    with record_phase("savings_baseline"):
        baseline_rows = simulate_baseline_horizon(
            matrix, baseline_soc, charging_contexts=charging_contexts, consumers=consumers
        )
    matched_targets = resolve_matched_baseline_horizon_targets(
        matrix,
        targets,
        charging_contexts,
        consumers=consumers,
    )
    with record_phase("savings_matched"):
        matched_baseline_rows = simulate_matched_baseline_horizon(
            matrix,
            baseline_soc,
            matched_targets,
            charging_contexts,
            consumers=consumers,
        )
    # Same base as resolve_matched_baseline_horizon_targets, without the profile fallback.
    costed_targets = apply_horizon_charging_limits(
        resolve_horizon_consumer_targets_kwh(matrix, targets, flexible_consumers=consumers),
        charging_contexts or {},
    )
    fallback_kwh = _profile_fallback_kwh(matched_targets, costed_targets)
    if fallback_kwh:
        with record_phase("savings_matched_costed"):
            matched_costed_rows = simulate_matched_baseline_horizon(
                matrix,
                baseline_soc,
                costed_targets,
                charging_contexts,
                consumers=consumers,
            )
    else:
        matched_costed_rows = matched_baseline_rows
    return _SavingsRows(
        optimized_rows,
        baseline_rows,
        matched_baseline_rows,
        matched_costed_rows,
        fallback_kwh,
    )


def _savings_cost_block(rows: _SavingsRows) -> dict:
    """Kosten- und Verbrauchssummen der drei Vergleichsläufe."""
    sell_price_cent = None
    optimized_cost = calculate_cost_euro_from_rows(rows.optimized, sell_price_cent)
    baseline_cost = calculate_cost_euro_from_rows(rows.baseline, sell_price_cent)
    matched_baseline_cost = calculate_cost_euro_from_rows(
        rows.matched_baseline_costed, sell_price_cent
    )
    savings = baseline_cost - optimized_cost
    savings_matched_euro = matched_baseline_cost - optimized_cost
    baseline_kwh = total_consumption_kwh_from_rows(rows.baseline)
    matched_baseline_kwh = total_consumption_kwh_from_rows(rows.matched_baseline_costed)
    optimized_kwh = total_consumption_kwh_from_rows(rows.optimized)
    return {
        "baseline_cost_euro": round(baseline_cost, 4),
        "matched_baseline_cost_euro": round(matched_baseline_cost, 4),
        "optimized_cost_euro": round(optimized_cost, 4),
        "savings_euro": round(savings, 4),
        "savings_matched_euro": round(savings_matched_euro, 4),
        "baseline_consumption_kwh": round(baseline_kwh, 3),
        "matched_baseline_consumption_kwh": round(matched_baseline_kwh, 3),
        "optimized_consumption_kwh": round(optimized_kwh, 3),
    }


def _savings_target_block(
    matrix: list,
    targets: dict[str, float] | None,
    rows: _SavingsRows,
    consumers: list | None,
) -> dict:
    """Baseline-/angewandte Ziele und der Energievergleich je Verbraucher."""
    from optimizer.targets import (
        build_applied_targets_detail,
        build_baseline_targets_detail,
        build_energy_comparison_detail,
    )

    applied_targets = build_applied_targets_detail(
        matrix,
        targets,
        consumers=consumers,
    )
    baseline_targets = build_baseline_targets_detail(matrix, consumers=consumers)
    matched_flex_kwh = (
        delivered_flex_kwh_from_rows(
            rows.matched_baseline, flexible_consumers=consumers
        )
        if rows.matched_baseline
        else None
    )
    energy_comparison = build_energy_comparison_detail(
        matrix,
        targets,
        matched_flex_kwh=matched_flex_kwh,
        profile_fallback_kwh=rows.profile_fallback_kwh,
        consumers=consumers,
    )
    return {
        "baseline_targets": baseline_targets,
        "applied_targets": applied_targets,
        "energy_comparison": energy_comparison,
    }


def _savings_hourly_block(rows: _SavingsRows, baseline_same_flex_rows: list) -> dict:
    """Stündliche Kosten-, Einsparungs- und Verbrauchsreihen."""
    sell_price_cent = None
    hourly_matched_cost = hourly_cost_euro_from_rows(
        rows.matched_baseline_costed, sell_price_cent
    )
    hourly_optimized_cost = hourly_cost_euro_from_rows(rows.optimized, sell_price_cent)
    hourly_savings = hourly_savings_euro_from_rows(
        rows.matched_baseline_costed, rows.optimized, sell_price_cent
    )
    hourly_battery_only_cost = hourly_cost_euro_from_rows(
        baseline_same_flex_rows, sell_price_cent
    )
    return {
        "hourly_matched_baseline_cost_euro": hourly_matched_cost,
        "hourly_optimized_cost_euro": hourly_optimized_cost,
        "hourly_battery_only_baseline_cost_euro": hourly_battery_only_cost,
        "hourly_savings_euro": hourly_savings,
        "hourly_matched_baseline_consumption_kwh": hourly_consumption_kwh_from_rows(
            rows.matched_baseline_costed
        ),
        "hourly_optimized_consumption_kwh": hourly_consumption_kwh_from_rows(
            rows.optimized
        ),
    }


def _shadow_chain_block(rows: _SavingsRows, costs: dict, baseline_soc: float) -> dict:
    """Saving figures for baselines on the shadow chain: the start energy must not count (Ledger P11)."""
    from optimizer.sim_baseline import _baseline_battery_params

    battery = _baseline_battery_params(None)
    increments = soc_correction_increments_euro(
        rows.optimized, rows.matched_baseline_costed, battery
    )
    correction = round(sum(increments), 4)
    free_correction = sum(soc_correction_increments_euro(rows.optimized, rows.baseline, battery))
    return {
        "savings_euro": round(costs["savings_euro"] + free_correction, 4),
        "savings_matched_euro": round(costs["savings_matched_euro"] + correction, 4),
        "plan_soc_correction_euro": correction,
        "hourly_soc_correction_euro": increments,
        "baseline_start_source": BASELINE_START_SHADOW_CHAIN,
        "baseline_start_soc_percent": round(float(baseline_soc), 2),
    }


def _assemble_savings_dict(
    matrix: list,
    initial_soc: float,
    baseline_soc: float,
    on_shadow_chain: bool,
    targets: dict[str, float] | None,
    charging_contexts: dict[str, dict] | None,
    rows: _SavingsRows,
    consumers: list | None,
) -> dict:
    """Fügt Kosten, Ziele, Simulationszeilen und Stundenreihen zum Payload zusammen."""
    from optimizer.charging_context import serialize_charging_contexts
    from optimizer.sim_baseline import simulate_baseline_with_optimized_flex
    from optimizer.targets import resolve_baseload_kwh

    costs = _savings_cost_block(rows)
    start_block = (
        _shadow_chain_block(rows, costs, baseline_soc)
        if on_shadow_chain
        else {"baseline_start_source": BASELINE_START_LIVE_SOC}
    )
    target_details = _savings_target_block(matrix, targets, rows, consumers)
    baseline_same_flex_rows = simulate_baseline_with_optimized_flex(
        matrix,
        rows.optimized,
        baseline_soc,
        consumers=consumers,
    )
    return {
        **costs,
        **start_block,
        "baseload_kwh": resolve_baseload_kwh(matrix),
        **target_details,
        "charging_contexts": serialize_charging_contexts(charging_contexts),
        "optimized_rows": rows.optimized,
        "baseline_rows": rows.baseline,
        "matched_baseline_rows": rows.matched_baseline,
        "matched_baseline_profile_fallback_kwh": dict(rows.profile_fallback_kwh),
        "baseline_same_flex_rows": baseline_same_flex_rows,
        **_savings_hourly_block(rows, baseline_same_flex_rows),
    }


def calculate_optimization_savings(
    optimization_matrix: list,
    initial_soc: float,
    consumer_daily_targets_kwh: dict[str, float] | None = None,
    sunrise_soc_min_index: int | None = None,
    filter_contexts: dict[str, dict] | None = None,
    consumers: list | None = None,
    current_soc_by_id: dict[str, float] | None = None,
    baseline_initial_soc: float | None = None,
) -> dict:
    """Berechnet die Einsparung in Euro gegenüber einer nicht-optimierten Baseline-Simulation.

    Optimized path uses open-loop ``commit_hours=len(matrix)`` (one MILP), not
    per-slot MPC — Live control already solved once; savings/charts must stay fast
    on QH horizons (~188 slots).

    ``baseline_initial_soc`` is the savings ledger's shadow SoC (Ledger P11): the
    baselines start there, the plan at ``initial_soc``, and the saving figures take out
    the value of the SoC gap (``soc_correction_increments_euro``). ``None`` means no
    chain: all runs start at ``initial_soc``, and ``baseline_start_source`` says so,
    so the chart can leave out the baseline's SoC line.
    """
    from optimizer.charge_immediate import prepare_optimization_matrix
    from optimizer.filter_context import resolve_filter_contexts

    matrix, charging_contexts, targets = prepare_optimization_matrix(
        optimization_matrix,
        consumer_daily_targets_kwh,
        consumers=consumers,
    )
    filters = filter_contexts or resolve_filter_contexts(matrix, consumers)
    on_shadow_chain = baseline_initial_soc is not None
    baseline_soc = float(baseline_initial_soc) if on_shadow_chain else initial_soc
    rows = _run_savings_horizons(
        matrix,
        initial_soc,
        baseline_soc,
        targets,
        charging_contexts,
        filters,
        sunrise_soc_min_index=sunrise_soc_min_index,
        consumers=consumers,
        current_soc_by_id=current_soc_by_id,
    )
    return _assemble_savings_dict(
        matrix,
        initial_soc,
        baseline_soc,
        on_shadow_chain,
        targets,
        charging_contexts,
        rows,
        consumers,
    )
