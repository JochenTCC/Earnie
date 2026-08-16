"""Baseline and matched-baseline horizon simulation."""
from __future__ import annotations

import config
from settings.flexible_consumers import flex_kw_lookup
from optimizer import battery as bat
from optimizer.slot_duration import DEFAULT_DT_H
from optimizer.sim_chart_rows import (
    _chart_price_fields,
    _chart_row_slot_field,
    _finalize_chart_rows_for_display,
    _format_chart_uhrzeit,
)
from optimizer.targets import consumer_column_name


def _matched_baseline_profile_kw(row: dict, consumer: dict) -> float:
    """Flex kW used as matched-baseline *shape*.

    ``live_snapshot`` is the current meter reading, not a historical day profile.
    Scaling a full horizon target onto that single QH sample yields
    ``target / dt_h`` kW (factor 4 at ``DEFAULT_DT_H=0.25``) and inflated BL Ziel €.
    """
    if row.get("consumption_mode") == "live_snapshot":
        return 0.0
    return flex_kw_lookup(row.get("expected_flex_kw") or {}, consumer)


def build_matched_flex_kw_per_hour(
    optimization_matrix: list,
    consumer_targets_kwh: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
) -> list[dict[str, float]]:
    """
    Skaliert das historische Flex-Profil auf die aktuellen Horizont-Ziele (kWh).
    Zeitliche Form bleibt erhalten (auch unter Nennleistung); außerhalb des
    Ladezeitfensters null – wie im MILP. Live-Snapshot-Slots zählen nicht als Profil.
    """
    # Resolve via simulation facade so tests can monkeypatch
    # ``optimizer.simulation.config`` / ``consumer_charging_eligible_indices``.
    from optimizer import simulation as sim

    consumers_cfg = sim.config.get_flexible_consumers(optimizer_only=True)
    rows = optimization_matrix
    hour_count = len(rows)
    contexts = charging_contexts or {}
    schedule_indices = list(range(hour_count))

    eligible_by_consumer: dict[str, set[int]] = {}
    for consumer in consumers_cfg:
        cid = consumer["id"]
        eligible = sim.consumer_charging_eligible_indices(
            rows,
            consumer,
            schedule_indices,
            contexts.get(cid),
        )
        eligible_by_consumer[cid] = set(eligible)

    profile_sums: dict[str, float] = {c["id"]: 0.0 for c in consumers_cfg}
    for consumer in consumers_cfg:
        cid = consumer["id"]
        eligible = eligible_by_consumer[cid]
        for t, row in enumerate(rows):
            if t not in eligible:
                continue
            profile_sums[cid] += _matched_baseline_profile_kw(row, consumer)

    per_hour: list[dict[str, float]] = []
    for t, row in enumerate(rows):
        hour_flex: dict[str, float] = {}
        for consumer in consumers_cfg:
            cid = consumer["id"]
            target = float(consumer_targets_kwh.get(cid, 0.0) or 0.0)
            eligible = eligible_by_consumer[cid]
            if t not in eligible:
                hour_flex[cid] = 0.0
                continue
            eligible_count = len(eligible)
            profile_sum = profile_sums[cid]
            profile_val = _matched_baseline_profile_kw(row, consumer)
            if profile_sum > 1e-6:
                # target is kWh; profile_sum is Σ kW → scale so Σ(kW)*dt_h = target
                hour_flex[cid] = profile_val * (
                    target / (profile_sum * float(DEFAULT_DT_H))
                )
            elif target > 0 and eligible_count > 0:
                hour_flex[cid] = target / (eligible_count * float(DEFAULT_DT_H))
            else:
                hour_flex[cid] = 0.0
        per_hour.append(hour_flex)
    return per_hour


def _simulate_single_hour_baseline(
    row: dict,
    sim_soc: float,
    battery_params: dict,
    flex_kw_override: dict[str, float] | None = None,
    steuerbefehl: str = "Baseline",
    baseload_kw_override: float | None = None,
) -> tuple[float, dict]:
    """Simuliert eine einzelne Stunde im Baseline-Pfad."""
    pv = row["expected_p_pv"]
    flex_kw = flex_kw_override if flex_kw_override is not None else (row.get("expected_flex_kw") or {})
    has_flex_profile = any(float(v or 0.0) > 0.0 for v in flex_kw.values())
    simulation_mode = row.get("consumption_mode") in ("logged_day", "profile_spec")
    if flex_kw_override is None and simulation_mode and not has_flex_profile:
        con = float(row.get("expected_p_total", row["expected_p_act"]) or 0.0)
        con = con + bat.standby_power_kw(battery_params)
        total_flex_power = 0.0
        flex_kw = {}
    elif baseload_kw_override is not None:
        con = float(baseload_kw_override) + bat.standby_power_kw(battery_params)
        total_flex_power = sum(float(v or 0.0) for v in flex_kw.values())
    else:
        con = bat.effective_p_act(row, battery_params)
        total_flex_power = sum(float(v or 0.0) for v in flex_kw.values())
    net_pv_surplus = pv - con - total_flex_power
    batt_action = bat.clamp_power(net_pv_surplus, battery_params["max_power_kw"])
    old_soc = sim_soc
    sim_soc, batt_action = bat.apply_soc_change(
        old_soc,
        batt_action,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
        dt_h=DEFAULT_DT_H,
    )
    p_grid = con + total_flex_power - pv + round(batt_action, 2)
    chart_row = {
        "Uhrzeit": _format_chart_uhrzeit(row),
        **_chart_row_slot_field(row),
        **_chart_price_fields(row),
        "PV-Prognose (kW)": pv,
        "Verbrauch-Prognose (kW)": con,
        "Geplante Batterie-Aktion (kW)": round(batt_action, 2),
        "Netzbezug (kW)": round(p_grid, 2),
        "Simulierter SoC (%)": round(old_soc, 1),
        "Steuerbefehl": steuerbefehl,
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        if flex_kw:
            chart_row[consumer_column_name(consumer)] = round(
                float(flex_kw.get(consumer["id"], 0.0) or 0.0), 2
            )
    return sim_soc, chart_row


def simulate_baseline_horizon(
    optimization_matrix: list,
    initial_soc: float,
    charging_contexts: dict[str, dict] | None = None,
    *,
    battery_params: dict | None = None,
) -> list:
    """Simuliert den 24h-Verlauf ohne Optimierung: Batterie folgt nur dem aktuellen PV-Überschuss."""
    chart_rows = []
    sim_soc = initial_soc
    battery_params = battery_params or config.get_battery_params()
    for row in optimization_matrix:
        sim_soc, chart_row = _simulate_single_hour_baseline(row, sim_soc, battery_params)
        chart_rows.append(chart_row)
    _finalize_chart_rows_for_display(chart_rows, charging_contexts)
    return chart_rows


def _flex_kw_from_chart_row(chart_row: dict) -> dict[str, float]:
    """Flex-Leistungen je Verbraucher aus einer Simulationszeile."""
    return {
        consumer["id"]: float(chart_row.get(consumer_column_name(consumer), 0.0) or 0.0)
        for consumer in config.get_flexible_consumers(optimizer_only=True)
    }


def simulate_baseline_with_optimized_flex(
    optimization_matrix: list,
    optimized_rows: list,
    initial_soc: float,
    *,
    battery_params: dict | None = None,
) -> list:
    """
    Baseline-Batterie (nur PV-Überschuss), aber dieselbe stündliche Flex-Last wie optimiert.
    Für den stündlichen Kostenvergleich: gleiche Last, Unterschied nur Batterie/Netz.
    """
    battery_params = battery_params or config.get_battery_params()
    sim_soc = initial_soc
    chart_rows: list[dict] = []
    for row, optimized_row in zip(optimization_matrix, optimized_rows):
        sim_soc, chart_row = _simulate_single_hour_baseline(
            row,
            sim_soc,
            battery_params,
            flex_kw_override=_flex_kw_from_chart_row(optimized_row),
            steuerbefehl="Baseline (Ziel)",
            baseload_kw_override=float(
                optimized_row.get("Verbrauch-Prognose (kW)", row["expected_p_act"]) or 0.0
            ),
        )
        chart_rows.append(chart_row)
    return chart_rows


def simulate_matched_baseline_horizon(
    optimization_matrix: list,
    initial_soc: float,
    consumer_targets_kwh: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    *,
    battery_params: dict | None = None,
) -> list:
    """
    Baseline mit gleicher Flex-Energie wie die Optimierung,
    aber ohne Preis-Lastverschiebung – Batterie nur PV-Überschuss.
    """
    matched_flex = build_matched_flex_kw_per_hour(
        optimization_matrix,
        consumer_targets_kwh,
        charging_contexts,
    )
    chart_rows = []
    sim_soc = initial_soc
    battery_params = battery_params or config.get_battery_params()
    for row, flex_kw in zip(optimization_matrix, matched_flex):
        sim_soc, chart_row = _simulate_single_hour_baseline(
            row,
            sim_soc,
            battery_params,
            flex_kw_override=flex_kw,
            steuerbefehl="Baseline (Ziel)",
        )
        chart_rows.append(chart_row)
    _finalize_chart_rows_for_display(chart_rows, charging_contexts)
    return chart_rows
