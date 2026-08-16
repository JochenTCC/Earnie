"""Horizont-Simulation (optimiert, Baseline) und Kostenberechnung."""
from __future__ import annotations

import logging

import config
from .cbc_events import (
    begin_cbc_event_collection,
    cbc_event_collection_active,
    clear_cbc_milp_context,
    set_cbc_milp_context,
    summarize_cbc_events,
    take_cbc_events,
)
from .charging_context import (
    apply_horizon_charging_limits,
    consumer_charging_eligible_indices,
    resolve_charging_contexts,
)
from . import battery as bat
from .generic_flex_run import continue_on_from_state, update_generic_flex_run_state
from .filter_context import adjust_targets_for_native_filter, resolve_filter_contexts
from .milp import milp_horizon_schedule, milp_optimizer
from .slot_duration import DEFAULT_DT_H, slots_for_wall_hours, validate_dt_h
from .targets import (
    consumer_column_name,
    resolve_horizon_consumer_targets_kwh,
)
from .sim_chart_rows import (
    _chart_row_from_controls,
    _chart_row_from_schedule_slot,
    _finalize_chart_rows_for_display,
    finalize_chart_row_energy,
    flexible_consumer_power_kw,
    horizon_end_soc_from_chart_rows,
    horizon_end_soc_percent,
    resolve_sell_price_cent,
    sync_chart_row_netzbezug,
)
from .sim_baseline import (
    _flex_kw_from_chart_row,
    _matched_baseline_profile_kw,
    _simulate_single_hour_baseline,
    build_matched_flex_kw_per_hour,
    simulate_baseline_horizon,
    simulate_baseline_with_optimized_flex,
    simulate_matched_baseline_horizon,
)
from .sim_costs import (
    _grid_kw_from_row,
    _round_savings_list,
    build_savings_snapshot,
    calculate_cost_euro_from_rows,
    calculate_optimization_savings,
    calculate_step_cost_euro_from_row,
    calculate_step_cost_parts_from_row,
    delivered_flex_kwh_from_rows,
    hourly_consumption_kwh_from_rows,
    hourly_cost_euro_from_rows,
    hourly_savings_euro_from_rows,
    total_consumption_kwh_from_rows,
)

logger = logging.getLogger(__name__)


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
    filter_contexts: dict[str, dict] | None,
    terminal_soc_percent: float | None,
    sunrise_soc_min_index: int | None,
    matrix_hour_index: int,
    flexible_consumers: list | None = None,
    consumer_continue_on: dict[str, bool] | None = None,
    soc_hold_index: int | None = None,
    soc_hold_percent: float | None = None,
) -> tuple[float, dict, int, float]:
    """Simuliert eine einzelne Stunde im optimierten Pfad (Huawei-Logik für die Batterie)."""
    h = row["hour"]
    rel_sunrise = _relative_sunrise_index(
        sunrise_soc_min_index,
        matrix_hour_index,
        len(remaining_matrix),
    )
    rel_hold = _relative_sunrise_index(
        soc_hold_index,
        matrix_hour_index,
        len(remaining_matrix),
    )
    consumers_cfg = flexible_consumers or config.get_flexible_consumers(optimizer_only=True)
    mode, target_power, target_soc, consumer_powers, consumer_pv_follow, _, _ = milp_optimizer(
        remaining_matrix,
        h,
        sim_soc,
        battery_params=battery_params,
        k_push=k_push,
        verbose=verbose,
        consumers=consumers_cfg,
        consumer_remaining_kwh=consumer_remaining_kwh,
        spa_remaining_kwh=spa_remaining_kwh,
        flex_indices=flex_indices,
        charging_contexts=charging_contexts,
        filter_contexts=filter_contexts,
        terminal_soc_percent=terminal_soc_percent,
        sunrise_soc_min_index=rel_sunrise,
        consumer_continue_on=consumer_continue_on,
        soc_hold_index=rel_hold,
        soc_hold_percent=soc_hold_percent if rel_hold is not None else None,
    )
    return _chart_row_from_controls(
        row,
        sim_soc,
        battery_params,
        consumers_cfg,
        mode,
        target_power,
        consumer_powers,
        consumer_pv_follow,
    )


def _commit_slots_for_buffer(
    commit_hours: int,
    *,
    matrix_len: int,
    remaining_len: int,
) -> int:
    """Wall-clock commit_hours → QH slot count; open-loop when >= matrix_len."""
    if commit_hours >= matrix_len:
        return remaining_len
    return min(
        remaining_len,
        max(1, slots_for_wall_hours(float(commit_hours), DEFAULT_DT_H)),
    )


def _terminal_soc_for_commit(
    commit_hours: int,
    remaining_slice_len: int,
    horizon_terminal_soc: float | None,
) -> float | None:
    """K=1: Terminal nur in der letzten Slot-Solve; K>1: Terminal solange Fensterende enthalten."""
    if horizon_terminal_soc is None:
        return None
    if commit_hours <= 1:
        return horizon_terminal_soc if remaining_slice_len == 1 else None
    return horizon_terminal_soc


def _flex_indices_for_book_hours(
    remaining_len: int,
    hour_index: int,
    flex_book_hours: int | None,
    flex_book_start: int = 0,
) -> list[int]:
    """
    Flex-eligible indices relative to remaining_slice.

    flex_book_hours=None: all remaining hours (Live / truncated SE).
    Otherwise only absolute hours [flex_book_start, flex_book_start + flex_book_hours).
    """
    if flex_book_hours is None:
        return list(range(remaining_len))
    if flex_book_hours < 1:
        raise ValueError(
            f"flex_book_hours must be >= 1 when set (got {flex_book_hours})."
        )
    if flex_book_start < 0:
        raise ValueError(
            f"flex_book_start must be >= 0 (got {flex_book_start})."
        )
    book_end = flex_book_start + flex_book_hours
    return [
        index
        for index in range(remaining_len)
        if flex_book_start <= hour_index + index < book_end
    ]


def _cap_flex_delivery(
    chart_row: dict,
    consumers_cfg: list,
    horizon_limits: dict[str, float],
    delivered_horizon: dict[str, float],
    *,
    dt_h: float = DEFAULT_DT_H,
) -> bool:
    """Begrenzt Flex-Leistung auf verbleibendes Horizontziel; True wenn gekappt."""
    dt_h = validate_dt_h(dt_h)
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
        energy = power * dt_h
        if energy > room + 1e-6:
            power = room / dt_h
            chart_row[col] = round(power, 2)
            flex_capped = True
            energy = power * dt_h
        if energy > 0:
            delivered_horizon[cid] = already + energy
    return flex_capped


def _apply_forced_grid_recharge_at_horizon_end(
    chart_rows: list[dict],
    end_soc: float,
    *,
    battery_params: dict,
    horizon_anchor_soc: float,
) -> float:
    """
    Netz-Zwangsladen am Horizontende, wenn SoC auf SOC_min liegt und der
    Terminal-Anker (Simulations-initial_soc) darüber liegt.
    """
    if not chart_rows or battery_params.get("battery_capacity_kwh", 0.0) <= 0.0:
        return end_soc
    min_soc = float(battery_params["min_soc"])
    max_soc = float(battery_params["max_soc"])
    if end_soc > min_soc + bat.SOC_DELTA_THRESHOLD:
        return end_soc
    target = min(max_soc, float(horizon_anchor_soc))
    if target <= min_soc + bat.SOC_DELTA_THRESHOLD:
        return end_soc
    charge_kw = bat.charge_kw_for_hourly_soc(
        end_soc,
        target,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["max_power_kw"],
        min_soc,
        max_soc,
        dt_h=DEFAULT_DT_H,
    )
    if charge_kw <= 0.0:
        return end_soc

    last = chart_rows[-1]
    start_last = float(last["Simulierter SoC (%)"])
    batt_old = float(last.get("Geplante Batterie-Aktion (kW)", 0.0) or 0.0)
    new_end_soc, batt_new = bat.apply_soc_change(
        start_last,
        batt_old + charge_kw,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        min_soc,
        max_soc,
        dt_h=DEFAULT_DT_H,
    )
    last["Geplante Batterie-Aktion (kW)"] = round(batt_new, 2)
    # Steuerbefehl must match the applied charge power (after SoC clip / prior action).
    last["Steuerbefehl"] = bat.steuerbefehl_for_mode(
        bat.MODE_ZWANGS_LADEN, max(0.0, float(batt_new))
    )
    sync_chart_row_netzbezug(last)
    return round(new_end_soc, 1)


def simulate_horizon(
    optimization_matrix: list,
    initial_soc: float,
    battery_params: dict | None = None,
    k_push: float | None = None,
    verbose: bool = True,
    on_progress=None,
    consumer_daily_targets_kwh: dict[str, float] | None = None,
    charging_contexts: dict[str, dict] | None = None,
    filter_contexts: dict[str, dict] | None = None,
    matrix_prepared: bool = False,
    simulation_hour_offset: int | None = None,
    sunrise_soc_min_index: int | None = None,
    flexible_consumers: list | None = None,
    commit_hours: int = 1,
    disable_horizon_soc_anchor: bool = False,
    flex_book_hours: int | None = None,
    flex_book_start: int = 0,
    soc_hold_index: int | None = None,
    soc_hold_percent: float | None = None,
) -> list:
    """
    Simuliert einen Optimierungshorizont über die gesamte Matrix.

    commit_hours=1: re-solve every matrix slot (Live MPC).
    commit_hours=N (N>1): wall-clock hours → commit N/dt_h QH slots open-loop (SE).
    disable_horizon_soc_anchor: keine Terminal-/Sonnenaufgangs-SOC_min-Gleichheit.
    flex_book_hours / flex_book_start: Flex nur in Absolutstunden
    [flex_book_start, flex_book_start + flex_book_hours).
    soc_hold_*: optional hard SoC equality (SE SA₁ carry-in); survives disable_horizon_soc_anchor.
    """
    if commit_hours < 1:
        raise ValueError(
            f"commit_hours must be >= 1 (got {commit_hours}). "
            "Use 1 for per-slot re-opt or len(matrix) for open-loop."
        )
    if disable_horizon_soc_anchor:
        sunrise_soc_min_index = None
    consumers_cfg = flexible_consumers or config.get_flexible_consumers(optimizer_only=True)
    if not matrix_prepared:
        from .charge_immediate import prepare_optimization_matrix

        optimization_matrix, charging_contexts, targets = prepare_optimization_matrix(
            optimization_matrix,
            consumer_daily_targets_kwh,
            consumers=consumers_cfg,
        )
        if consumer_daily_targets_kwh is None:
            consumer_daily_targets_kwh = targets
    elif charging_contexts is None:
        charging_contexts = resolve_charging_contexts(
            optimization_matrix,
            consumer_daily_targets_kwh,
            consumers=consumers_cfg,
        )

    chart_rows = []
    sim_soc = initial_soc
    battery_params = battery_params or config.get_battery_params()
    total_steps = len(optimization_matrix)
    horizon_limits = resolve_horizon_consumer_targets_kwh(
        optimization_matrix,
        consumer_daily_targets_kwh,
        flexible_consumers=consumers_cfg,
    )
    charging_contexts = charging_contexts or resolve_charging_contexts(
        optimization_matrix,
        consumer_daily_targets_kwh,
        consumers=consumers_cfg,
    )
    horizon_limits = apply_horizon_charging_limits(horizon_limits, charging_contexts)
    filters = filter_contexts or resolve_filter_contexts(
        optimization_matrix, consumers_cfg
    )
    horizon_limits = adjust_targets_for_native_filter(
        horizon_limits, consumers_cfg, optimization_matrix, filters
    )
    delivered_horizon: dict[str, float] = {c["id"]: 0.0 for c in consumers_cfg}
    generic_flex_run: dict[str, dict] = {}
    if disable_horizon_soc_anchor:
        horizon_terminal_soc = None
    else:
        horizon_terminal_soc = (
            None if sunrise_soc_min_index is not None else initial_soc
        )
    commit_buffer: list[dict] = []
    buffer_pos = 0
    own_cbc_collection = not cbc_event_collection_active()
    if own_cbc_collection:
        begin_cbc_event_collection()
    try:
        hour_base = simulation_hour_offset or 0
        for i, row in enumerate(optimization_matrix):
            set_cbc_milp_context(simulation_hour_index=hour_base + i)
            remaining = {
                consumer["id"]: max(
                    0.0,
                    horizon_limits.get(consumer["id"], 0.0)
                    - delivered_horizon.get(consumer["id"], 0.0),
                )
                for consumer in consumers_cfg
            }
            remaining_slice = optimization_matrix[i:]
            continue_on = continue_on_from_state(
                {"generic_flex_run": generic_flex_run},
                consumers_cfg,
            )
            flex_indices = _flex_indices_for_book_hours(
                len(remaining_slice),
                i,
                flex_book_hours,
                flex_book_start,
            )
            if commit_hours <= 1:
                terminal_soc_percent = _terminal_soc_for_commit(
                    commit_hours, len(remaining_slice), horizon_terminal_soc
                )
                sim_soc, chart_row, mode, target_power = _simulate_single_hour_optimizer(
                    remaining_slice,
                    row,
                    sim_soc,
                    battery_params,
                    k_push=k_push,
                    verbose=verbose,
                    consumer_remaining_kwh=remaining,
                    spa_remaining_kwh=None,
                    flex_indices=flex_indices,
                    charging_contexts=charging_contexts,
                    filter_contexts=filters,
                    terminal_soc_percent=terminal_soc_percent,
                    sunrise_soc_min_index=sunrise_soc_min_index,
                    matrix_hour_index=i,
                    flexible_consumers=consumers_cfg,
                    consumer_continue_on=continue_on,
                    soc_hold_index=soc_hold_index,
                    soc_hold_percent=soc_hold_percent,
                )
            else:
                if buffer_pos >= len(commit_buffer):
                    rel_sunrise = _relative_sunrise_index(
                        sunrise_soc_min_index,
                        i,
                        len(remaining_slice),
                    )
                    rel_hold = _relative_sunrise_index(
                        soc_hold_index,
                        i,
                        len(remaining_slice),
                    )
                    terminal_soc_percent = _terminal_soc_for_commit(
                        commit_hours, len(remaining_slice), horizon_terminal_soc
                    )
                    schedule = milp_horizon_schedule(
                        remaining_slice,
                        sim_soc,
                        battery_params=battery_params,
                        k_push=k_push,
                        verbose=verbose,
                        consumers=consumers_cfg,
                        consumer_remaining_kwh=remaining,
                        flex_indices=flex_indices,
                        charging_contexts=charging_contexts,
                        filter_contexts=filters,
                        terminal_soc_percent=terminal_soc_percent,
                        sunrise_soc_min_index=rel_sunrise,
                        consumer_continue_on=continue_on,
                        soc_hold_index=rel_hold,
                        soc_hold_percent=(
                            soc_hold_percent if rel_hold is not None else None
                        ),
                    )
                    commit_slots = _commit_slots_for_buffer(
                        commit_hours,
                        matrix_len=len(optimization_matrix),
                        remaining_len=len(schedule),
                    )
                    commit_buffer = schedule[:commit_slots]
                    buffer_pos = 0
                slot = commit_buffer[buffer_pos]
                buffer_pos += 1
                sim_soc, chart_row, mode, target_power = _chart_row_from_schedule_slot(
                    row,
                    sim_soc,
                    battery_params,
                    consumers_cfg,
                    slot,
                )
            _cap_flex_delivery(
                chart_row, consumers_cfg, horizon_limits, delivered_horizon
            )
            for consumer in consumers_cfg:
                power = float(
                    chart_row.get(consumer_column_name(consumer), 0.0) or 0.0
                )
                update_generic_flex_run_state(generic_flex_run, consumer, power)
            old_soc = float(chart_row["Simulierter SoC (%)"])
            sim_soc = finalize_chart_row_energy(
                chart_row, mode, target_power, old_soc, battery_params
            )
            chart_rows.append(chart_row)
            if on_progress is not None:
                on_progress(i + 1, total_steps)
    finally:
        if own_cbc_collection:
            summary = summarize_cbc_events(take_cbc_events())
            if summary:
                logger.info(summary)
            clear_cbc_milp_context()
    if sunrise_soc_min_index is None and not disable_horizon_soc_anchor:
        sim_soc = _apply_forced_grid_recharge_at_horizon_end(
            chart_rows,
            sim_soc,
            battery_params=battery_params,
            horizon_anchor_soc=initial_soc,
        )
    _finalize_chart_rows_for_display(chart_rows, charging_contexts)
    if chart_rows:
        chart_rows[-1]["_horizon_end_soc"] = horizon_end_soc_percent(
            chart_rows,
            initial_soc,
            battery_params,
        )
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


# Re-Exports für API-Stabilität (from optimizer.simulation import ...)
__all__ = [
    "_apply_forced_grid_recharge_at_horizon_end",
    "_cap_flex_delivery",
    "_chart_row_from_controls",
    "_chart_row_from_schedule_slot",
    "_commit_slots_for_buffer",
    "_finalize_chart_rows_for_display",
    "_flex_indices_for_book_hours",
    "_flex_kw_from_chart_row",
    "_grid_kw_from_row",
    "_matched_baseline_profile_kw",
    "_relative_sunrise_index",
    "_round_savings_list",
    "_simulate_single_hour_baseline",
    "_simulate_single_hour_optimizer",
    "_terminal_soc_for_commit",
    "build_matched_flex_kw_per_hour",
    "build_savings_snapshot",
    "calculate_cost_euro_from_rows",
    "calculate_optimization_savings",
    "calculate_step_cost_euro_from_row",
    "calculate_step_cost_parts_from_row",
    "delivered_flex_kwh_from_rows",
    "finalize_chart_row_energy",
    "flexible_consumer_power_kw",
    "horizon_end_soc_from_chart_rows",
    "horizon_end_soc_percent",
    "hourly_consumption_kwh_from_rows",
    "hourly_cost_euro_from_rows",
    "hourly_savings_euro_from_rows",
    "resolve_sell_price_cent",
    "simulate_24h_horizon",
    "simulate_baseline_horizon",
    "simulate_baseline_with_optimized_flex",
    "simulate_horizon",
    "simulate_matched_baseline_horizon",
    "sync_chart_row_netzbezug",
    "total_consumption_kwh_from_rows",
]
