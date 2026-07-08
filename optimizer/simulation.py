"""Horizont-Simulation (optimiert, Baseline) und Kostenberechnung."""
from __future__ import annotations

from datetime import datetime

import config
from .charging_context import (
    apply_horizon_charging_limits,
    consumer_charging_eligible_indices,
    resolve_charging_contexts,
)
from . import battery as bat
from .consumer_power import uses_pv_follow
from .filter_context import adjust_targets_for_native_filter
from .milp import milp_optimizer
from .targets import (
    build_applied_targets_detail,
    build_baseline_targets_detail,
    build_energy_comparison_detail,
    consumer_column_name,
    consumer_pv_follow_column_name,
    resolve_baseload_kwh,
    resolve_horizon_consumer_targets_kwh,
)

from data.price_forecast_live import is_extrapolated_source


def _chart_price_fields(row: dict) -> dict:
    """Preis-Felder für Simulations-/Chart-Zeilen."""
    fields = {
        "Strompreis (Cent/kWh)": row["k_act"],
        "Preis extrapoliert": is_extrapolated_source(row.get("price_source")),
    }
    if "k_push_act" in row:
        fields["Einspeisevergütung (Cent/kWh)"] = row["k_push_act"]
    return fields


def resolve_sell_price_cent(row: dict, default_sell_price_cent: float | None = None) -> float:
    """Stündliche Einspeisevergütung aus Chart-Zeile oder Fallback."""
    if "Einspeisevergütung (Cent/kWh)" in row:
        return float(row["Einspeisevergütung (Cent/kWh)"])
    if default_sell_price_cent is not None:
        return float(default_sell_price_cent)
    raise ValueError(
        "Kein Einspeisepreis in der Zeile und kein Fallback angegeben "
        "(Einspeisevergütung (Cent/kWh) oder default_sell_price_cent)."
    )


_RESERVED_KW_COLUMNS = {
    "PV-Prognose (kW)",
    "Verbrauch-Prognose (kW)",
    "Geplante Batterie-Aktion (kW)",
    "Netzbezug (kW)",
}


def flexible_consumer_power_kw(row: dict) -> float:
    """Summiert alle flexiblen Verbraucher-Leistungen aus einer Chart-Zeile."""
    return sum(
        float(value or 0.0)
        for key, value in row.items()
        if key.endswith(" (kW)") and key not in _RESERVED_KW_COLUMNS
    )


def _format_chart_uhrzeit(row: dict) -> str:
    slot_dt = row.get("slot_datetime")
    if isinstance(slot_dt, datetime):
        return slot_dt.strftime("%d.%m. %H:%M")
    hour = row.get("hour", 0)
    return f"{int(hour):02d}:00"


def _chart_row_slot_field(row: dict) -> dict:
    slot_dt = row.get("slot_datetime")
    if isinstance(slot_dt, datetime):
        return {"slot_datetime": slot_dt}
    return {}


def _relative_sunrise_index(
    sunrise_soc_min_index: int | None,
    slice_start: int,
    slice_len: int,
) -> int | None:
    if sunrise_soc_min_index is None:
        return None
    if sunrise_soc_min_index < slice_start:
        return None
    rel = sunrise_soc_min_index - slice_start
    if rel < 0 or rel >= slice_len:
        return None
    return rel


def _simulate_single_hour_optimizer(
    remaining_matrix: list,
    row: dict,
    sim_soc: float,
    battery_params: dict,
    k_push: float | None,
    verbose: bool,
    consumer_remaining_kwh: dict[str, float] | None,
    spa_remaining_kwh: float | None,
    flex_indices: list[int] | None,
    charging_contexts: dict[str, dict] | None,
    terminal_soc_percent: float | None,
    sunrise_soc_min_index: int | None,
    matrix_hour_index: int,
) -> tuple[float, dict, int, float]:
    """Simuliert eine einzelne Stunde im optimierten Pfad (Huawei-Logik für die Batterie)."""
    h = row["hour"]
    rel_sunrise = _relative_sunrise_index(
        sunrise_soc_min_index,
        matrix_hour_index,
        len(remaining_matrix),
    )
    mode, target_power, target_soc, consumer_powers, consumer_pv_follow, _, _ = milp_optimizer(
        remaining_matrix,
        h,
        sim_soc,
        battery_params=battery_params,
        k_push=k_push,
        verbose=verbose,
        consumer_remaining_kwh=consumer_remaining_kwh,
        spa_remaining_kwh=spa_remaining_kwh,
        flex_indices=flex_indices,
        charging_contexts=charging_contexts,
        terminal_soc_percent=terminal_soc_percent,
        sunrise_soc_min_index=rel_sunrise,
    )
    pv = row["expected_p_pv"]
    con = row["expected_p_act"]
    total_flex_power = sum(consumer_powers.values())
    max_power = battery_params["max_power_kw"]
    batt_action = bat.battery_plan_kw_from_control(
        mode, target_power, pv, con, total_flex_power, max_power
    )
    action_text = bat.steuerbefehl_for_mode(mode, target_power)
    old_soc = sim_soc
    sim_soc, batt_action = bat.apply_soc_change(
        old_soc,
        batt_action,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
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
        "Steuerbefehl": action_text,
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        chart_row[consumer_column_name(consumer)] = round(
            consumer_powers.get(consumer["id"], 0.0), 2
        )
        if uses_pv_follow(consumer):
            chart_row[consumer_pv_follow_column_name(consumer)] = int(
                consumer_pv_follow.get(consumer["id"], 0) or 0
            )
    return sim_soc, chart_row, mode, target_power


def _cap_flex_delivery(
    chart_row: dict,
    consumers_cfg: list,
    horizon_limits: dict[str, float],
    delivered_horizon: dict[str, float],
) -> bool:
    """Begrenzt Flex-Leistung auf verbleibendes Horizontziel; True wenn gekappt."""
    flex_capped = False
    for consumer in consumers_cfg:
        col = consumer_column_name(consumer)
        cid = consumer["id"]
        power = float(chart_row.get(col, 0.0) or 0.0)
        if power <= 0:
            continue
        max_kwh = horizon_limits.get(cid, 0.0)
        already = delivered_horizon.get(cid, 0.0)
        room = max(0.0, max_kwh - already)
        if power > room + 1e-6:
            power = room
            chart_row[col] = round(power, 2)
            flex_capped = True
        if power > 0:
            delivered_horizon[cid] = already + power
    return flex_capped


def finalize_chart_row_energy(
    chart_row: dict,
    mode: int,
    target_power: float,
    old_soc: float,
    battery_params: dict,
) -> float:
    """Leitet Batterieaktion, Netzbezug und End-SoC aus Zeileninhalt ab (Huawei-Logik)."""
    pv = float(chart_row["PV-Prognose (kW)"])
    con = float(chart_row["Verbrauch-Prognose (kW)"])
    total_flex = flexible_consumer_power_kw(chart_row)
    max_power = battery_params["max_power_kw"]
    batt_action = bat.battery_plan_kw_from_control(
        mode, target_power, pv, con, total_flex, max_power
    )
    new_soc, batt_action = bat.apply_soc_change(
        old_soc,
        batt_action,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
    )
    chart_row["Geplante Batterie-Aktion (kW)"] = round(batt_action, 2)
    chart_row["Netzbezug (kW)"] = round(
        con + total_flex - pv + chart_row["Geplante Batterie-Aktion (kW)"],
        2,
    )
    return new_soc


def sync_chart_row_netzbezug(chart_row: dict) -> None:
    """Netzbezug aus PV, Last, Flex und Batterie ableiten (Chart-Energiebilanz)."""
    pv = float(chart_row.get("PV-Prognose (kW)", 0.0) or 0.0)
    con = float(chart_row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
    batt = float(chart_row.get("Geplante Batterie-Aktion (kW)", 0.0) or 0.0)
    flex_sum = flexible_consumer_power_kw(chart_row)
    chart_row["Netzbezug (kW)"] = round(con + flex_sum - pv + batt, 2)


def simulate_horizon(
    optimization_matrix: list,
    initial_soc: float,
    battery_params: dict | None = None,
    k_push: float | None = None,
    verbose: bool = True,
    on_progress=None,
    consumer_daily_targets_kwh: dict[str, float] | None = None,
    charging_contexts: dict[str, dict] | None = None,
    matrix_prepared: bool = False,
    simulation_hour_offset: int | None = None,
    sunrise_soc_min_index: int | None = None,
) -> list:
    """Simuliert einen rollierenden Optimierungshorizont über die gesamte Matrix."""
    if not matrix_prepared:
        from .charge_immediate import prepare_optimization_matrix

        optimization_matrix, charging_contexts, targets = prepare_optimization_matrix(
            optimization_matrix,
            consumer_daily_targets_kwh,
        )
        if consumer_daily_targets_kwh is None:
            consumer_daily_targets_kwh = targets
    elif charging_contexts is None:
        charging_contexts = resolve_charging_contexts(
            optimization_matrix,
            consumer_daily_targets_kwh,
        )

    chart_rows = []
    sim_soc = initial_soc
    battery_params = battery_params or config.get_battery_params()
    total_steps = len(optimization_matrix)
    consumers_cfg = config.get_flexible_consumers(optimizer_only=True)
    horizon_limits = resolve_horizon_consumer_targets_kwh(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )
    charging_contexts = charging_contexts or resolve_charging_contexts(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )
    horizon_limits = apply_horizon_charging_limits(horizon_limits, charging_contexts)
    horizon_limits = adjust_targets_for_native_filter(
        horizon_limits, consumers_cfg, optimization_matrix
    )
    delivered_horizon: dict[str, float] = {c["id"]: 0.0 for c in consumers_cfg}
    terminal_soc_percent = None if sunrise_soc_min_index is not None else initial_soc
    for i, row in enumerate(optimization_matrix):
        if simulation_hour_offset is not None:
            from optimizer.cbc_events import set_cbc_milp_context

            set_cbc_milp_context(simulation_hour_index=simulation_hour_offset + i)
        remaining = {
            consumer["id"]: max(
                0.0,
                horizon_limits.get(consumer["id"], 0.0)
                - delivered_horizon.get(consumer["id"], 0.0),
            )
            for consumer in consumers_cfg
        }
        remaining_slice = optimization_matrix[i:]
        sim_soc, chart_row, mode, target_power = _simulate_single_hour_optimizer(
            remaining_slice,
            row,
            sim_soc,
            battery_params,
            k_push=k_push,
            verbose=verbose,
            consumer_remaining_kwh=remaining,
            spa_remaining_kwh=None,
            flex_indices=list(range(len(remaining_slice))),
            charging_contexts=charging_contexts,
            terminal_soc_percent=terminal_soc_percent,
            sunrise_soc_min_index=sunrise_soc_min_index,
            matrix_hour_index=i,
        )
        _cap_flex_delivery(
            chart_row, consumers_cfg, horizon_limits, delivered_horizon
        )
        old_soc = float(chart_row["Simulierter SoC (%)"])
        sim_soc = finalize_chart_row_energy(
            chart_row, mode, target_power, old_soc, battery_params
        )
        chart_rows.append(chart_row)
        if on_progress is not None:
            on_progress(i + 1, total_steps)
    from .charge_immediate import apply_immediate_charge_to_chart_rows

    apply_immediate_charge_to_chart_rows(chart_rows, charging_contexts)
    return chart_rows


def simulate_24h_horizon(
    optimization_matrix: list,
    initial_soc: float,
    consumer_daily_targets_kwh: dict[str, float] | None = None,
    verbose: bool = True,
    charging_contexts: dict[str, dict] | None = None,
    matrix_prepared: bool = False,
) -> list:
    """Simuliert den 24-Stunden-Verlauf des SoC."""
    return simulate_horizon(
        optimization_matrix[:24],
        initial_soc,
        consumer_daily_targets_kwh=consumer_daily_targets_kwh,
        verbose=verbose,
        charging_contexts=charging_contexts,
        matrix_prepared=matrix_prepared,
    )


def total_consumption_kwh_from_rows(rows: list) -> float:
    """
    Summiert den Stundenverbrauch (Grundlast + flexible Verbraucher) über alle Zeilen.
    Jede Zeile = 1 Stunde; kW-Werte werden als kWh addiert.
    """
    return round(
        sum(
            float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
            + flexible_consumer_power_kw(row)
            for row in rows
        ),
        3,
    )


def delivered_flex_kwh_from_rows(rows: list) -> dict[str, float]:
    """Summiert die gelieferte Flex-Energie je Verbraucher über alle Simulationsstunden."""
    totals: dict[str, float] = {}
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = consumer_column_name(consumer)
        totals[consumer["id"]] = round(
            sum(float(row.get(col, 0.0) or 0.0) for row in rows),
            3,
        )
    return totals


def calculate_step_cost_euro_from_row(
    row: dict,
    sell_price_cent: float | None = None,
) -> float:
    """Berechnet die Stromkosten einer einzelnen Simulationsstunde in Euro."""
    p_con = row["Verbrauch-Prognose (kW)"] + flexible_consumer_power_kw(row)
    price_cent = row["Strompreis (Cent/kWh)"]
    sell_cent = resolve_sell_price_cent(row, sell_price_cent)
    if "Netzbezug (kW)" in row:
        p_grid = float(row["Netzbezug (kW)"])
    else:
        p_pv = row["PV-Prognose (kW)"]
        batt_action = row["Geplante Batterie-Aktion (kW)"]
        p_grid = p_con - p_pv + batt_action
    if p_grid >= 0:
        step_cents = p_grid * price_cent
    else:
        step_cents = p_grid * sell_cent
    return step_cents / 100.0


def calculate_cost_euro_from_rows(rows: list, sell_price_cent: float | None = None) -> float:
    """Berechnet die Kosten in Euro für eine Stundenreihe aus einem Simulations-Output."""
    return sum(calculate_step_cost_euro_from_row(row, sell_price_cent) for row in rows)


def hourly_consumption_kwh_from_rows(rows: list) -> list[float]:
    """Stündlicher Gesamtverbrauch (Grundlast + Flex) in kWh je Simulationszeile."""
    return [
        round(
            float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
            + flexible_consumer_power_kw(row),
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


def build_matched_flex_kw_per_hour(
    optimization_matrix: list,
    consumer_targets_kwh: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
) -> list[dict[str, float]]:
    """
    Skaliert das historische Flex-Profil auf die aktuellen Horizont-Ziele (kWh).
    Zeitliche Form bleibt erhalten (auch unter Nennleistung); außerhalb des
    Ladezeitfensters null – wie im MILP.
    """
    consumers_cfg = config.get_flexible_consumers(optimizer_only=True)
    rows = optimization_matrix
    hour_count = len(rows)
    contexts = charging_contexts or {}
    schedule_indices = list(range(hour_count))

    eligible_by_consumer: dict[str, set[int]] = {}
    for consumer in consumers_cfg:
        cid = consumer["id"]
        eligible = consumer_charging_eligible_indices(
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
            flex = row.get("expected_flex_kw") or {}
            profile_sums[cid] += float(flex.get(cid, 0.0) or 0.0)

    per_hour: list[dict[str, float]] = []
    for t, row in enumerate(rows):
        flex = row.get("expected_flex_kw") or {}
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
            profile_val = float(flex.get(cid, 0.0) or 0.0)
            if profile_sum > 1e-6:
                hour_flex[cid] = profile_val * (target / profile_sum)
            elif target > 0 and eligible_count > 0:
                hour_flex[cid] = target / eligible_count
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
    h = row["hour"]
    pv = row["expected_p_pv"]
    flex_kw = flex_kw_override if flex_kw_override is not None else (row.get("expected_flex_kw") or {})
    has_flex_profile = any(float(v or 0.0) > 0.0 for v in flex_kw.values())
    logged_day = row.get("consumption_mode") == "logged_day"
    if flex_kw_override is None and logged_day and not has_flex_profile:
        con = float(row.get("expected_p_total", row["expected_p_act"]) or 0.0)
        total_flex_power = 0.0
        flex_kw = {}
    elif baseload_kw_override is not None:
        con = float(baseload_kw_override)
        total_flex_power = sum(float(v or 0.0) for v in flex_kw.values())
    else:
        con = float(row["expected_p_act"] or 0.0)
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
) -> list:
    """Simuliert den 24h-Verlauf ohne Optimierung: Batterie folgt nur dem aktuellen PV-Überschuss."""
    chart_rows = []
    sim_soc = initial_soc
    battery_params = config.get_battery_params()
    for row in optimization_matrix[:24]:
        sim_soc, chart_row = _simulate_single_hour_baseline(row, sim_soc, battery_params)
        chart_rows.append(chart_row)
    from .charge_immediate import apply_immediate_charge_to_chart_rows

    apply_immediate_charge_to_chart_rows(chart_rows, charging_contexts)
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
) -> list:
    """
    Baseline-Batterie (nur PV-Überschuss), aber dieselbe stündliche Flex-Last wie optimiert.
    Für den stündlichen Kostenvergleich: gleiche Last, Unterschied nur Batterie/Netz.
    """
    battery_params = config.get_battery_params()
    sim_soc = initial_soc
    chart_rows: list[dict] = []
    for row, optimized_row in zip(optimization_matrix[:24], optimized_rows[:24]):
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
    battery_params = config.get_battery_params()
    for row, flex_kw in zip(optimization_matrix, matched_flex):
        sim_soc, chart_row = _simulate_single_hour_baseline(
            row,
            sim_soc,
            battery_params,
            flex_kw_override=flex_kw,
            steuerbefehl="Baseline (Ziel)",
        )
        chart_rows.append(chart_row)
    from .charge_immediate import apply_immediate_charge_to_chart_rows

    apply_immediate_charge_to_chart_rows(chart_rows, charging_contexts)
    return chart_rows


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
) -> dict:
    """Berechnet die Einsparung in Euro gegenüber einer nicht-optimierten Baseline-Simulation."""
    from .charge_immediate import prepare_optimization_matrix
    from .charging_context import serialize_charging_contexts

    matrix, charging_contexts, targets = prepare_optimization_matrix(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )
    optimized_rows = simulate_horizon(
        matrix,
        initial_soc,
        consumer_daily_targets_kwh=targets,
        verbose=False,
        charging_contexts=charging_contexts,
        matrix_prepared=True,
        sunrise_soc_min_index=sunrise_soc_min_index,
    )
    baseline_rows = simulate_baseline_horizon(
        matrix, initial_soc, charging_contexts=charging_contexts
    )
    horizon_targets = resolve_horizon_consumer_targets_kwh(
        matrix,
        targets,
    )
    horizon_targets = apply_horizon_charging_limits(horizon_targets, charging_contexts)
    matched_baseline_rows = simulate_matched_baseline_horizon(
        matrix,
        initial_soc,
        horizon_targets,
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
