"""Horizont-Simulation (optimiert, Baseline) und Kostenberechnung."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import NamedTuple

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
from .generic_flex_run import continue_on_from_state, update_generic_flex_run_state
from .filter_context import adjust_targets_for_native_filter, resolve_filter_contexts
from .milp import milp_horizon_schedule, milp_optimizer
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
from .sim_horizon_helpers import (
    _apply_forced_grid_recharge_at_horizon_end,
    _cap_flex_delivery,
    _commit_slots_for_buffer,
    _flex_indices_for_book_hours,
    _relative_sunrise_index,
    _terminal_soc_for_commit,
)

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class _HorizonOptions:
    """Unveränderte ``simulate_horizon``-Steuerparameter für die Slot-Helfer."""

    k_push: float | None
    verbose: bool
    commit_hours: int
    flex_book_hours: int | None
    flex_book_start: int
    sunrise_soc_min_index: int | None
    soc_hold_index: int | None
    soc_hold_percent: float | None


@dataclass(frozen=True)
class _HorizonSetup:
    """Vorbereitete Matrix, Kontexte und Flex-Grenzen eines Horizontlaufs."""

    matrix: list
    consumers_cfg: list
    battery_params: dict
    charging_contexts: dict[str, dict] | None
    filters: dict[str, dict] | None
    horizon_limits: dict[str, float]
    horizon_terminal_soc: float | None
    options: _HorizonOptions


class _SlotInputs(NamedTuple):
    """Slot-abhängige MILP-Eingaben (Restmatrix, Restenergie, Flex-Fenster)."""

    remaining_slice: list
    remaining: dict[str, float]
    continue_on: dict[str, bool]
    flex_indices: list[int]


def _prepare_horizon_state(
    optimization_matrix: list,
    initial_soc: float,
    options: _HorizonOptions,
    *,
    battery_params: dict | None,
    consumer_daily_targets_kwh: dict[str, float] | None,
    charging_contexts: dict[str, dict] | None,
    filter_contexts: dict[str, dict] | None,
    matrix_prepared: bool,
    disable_horizon_soc_anchor: bool,
    flexible_consumers: list | None,
) -> _HorizonSetup:
    """Bereitet Matrix, Lade-/Filterkontexte, Flex-Horizontgrenzen und Terminal-SoC auf."""
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
    battery_params = battery_params or config.get_battery_params()
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
    if disable_horizon_soc_anchor:
        horizon_terminal_soc = None
    else:
        horizon_terminal_soc = (
            None if options.sunrise_soc_min_index is not None else initial_soc
        )
    return _HorizonSetup(
        matrix=optimization_matrix,
        consumers_cfg=consumers_cfg,
        battery_params=battery_params,
        charging_contexts=charging_contexts,
        filters=filters,
        horizon_limits=horizon_limits,
        horizon_terminal_soc=horizon_terminal_soc,
        options=options,
    )


def _slot_solve_inputs(
    setup: _HorizonSetup,
    hour_index: int,
    delivered_horizon: dict[str, float],
    generic_flex_run: dict[str, dict],
) -> _SlotInputs:
    """Restenergie, Restmatrix, offene min_on-Blöcke und Flex-Indizes für einen Slot."""
    remaining = {
        consumer["id"]: max(
            0.0,
            setup.horizon_limits.get(consumer["id"], 0.0)
            - delivered_horizon.get(consumer["id"], 0.0),
        )
        for consumer in setup.consumers_cfg
    }
    remaining_slice = setup.matrix[hour_index:]
    continue_on = continue_on_from_state(
        {"generic_flex_run": generic_flex_run},
        setup.consumers_cfg,
    )
    flex_indices = _flex_indices_for_book_hours(
        len(remaining_slice),
        hour_index,
        setup.options.flex_book_hours,
        setup.options.flex_book_start,
    )
    return _SlotInputs(remaining_slice, remaining, continue_on, flex_indices)


def _solve_slot_mpc(
    setup: _HorizonSetup,
    row: dict,
    sim_soc: float,
    hour_index: int,
    slot_in: _SlotInputs,
) -> tuple[float, dict, int, float]:
    """Slot-Neuoptimierung für ``commit_hours=1`` (Live-MPC)."""
    options = setup.options
    terminal_soc_percent = _terminal_soc_for_commit(
        options.commit_hours,
        len(slot_in.remaining_slice),
        setup.horizon_terminal_soc,
    )
    return _simulate_single_hour_optimizer(
        slot_in.remaining_slice,
        row,
        sim_soc,
        setup.battery_params,
        k_push=options.k_push,
        verbose=options.verbose,
        consumer_remaining_kwh=slot_in.remaining,
        spa_remaining_kwh=None,
        flex_indices=slot_in.flex_indices,
        charging_contexts=setup.charging_contexts,
        filter_contexts=setup.filters,
        terminal_soc_percent=terminal_soc_percent,
        sunrise_soc_min_index=options.sunrise_soc_min_index,
        matrix_hour_index=hour_index,
        flexible_consumers=setup.consumers_cfg,
        consumer_continue_on=slot_in.continue_on,
        soc_hold_index=options.soc_hold_index,
        soc_hold_percent=options.soc_hold_percent,
    )


def _refill_commit_buffer(
    setup: _HorizonSetup,
    sim_soc: float,
    hour_index: int,
    slot_in: _SlotInputs,
) -> list[dict]:
    """Open-Loop-MILP über die Restmatrix; liefert die festgeschriebenen Slots."""
    options = setup.options
    remaining_slice = slot_in.remaining_slice
    rel_sunrise = _relative_sunrise_index(
        options.sunrise_soc_min_index,
        hour_index,
        len(remaining_slice),
    )
    rel_hold = _relative_sunrise_index(
        options.soc_hold_index,
        hour_index,
        len(remaining_slice),
    )
    terminal_soc_percent = _terminal_soc_for_commit(
        options.commit_hours, len(remaining_slice), setup.horizon_terminal_soc
    )
    schedule = milp_horizon_schedule(
        remaining_slice,
        sim_soc,
        battery_params=setup.battery_params,
        k_push=options.k_push,
        verbose=options.verbose,
        consumers=setup.consumers_cfg,
        consumer_remaining_kwh=slot_in.remaining,
        flex_indices=slot_in.flex_indices,
        charging_contexts=setup.charging_contexts,
        filter_contexts=setup.filters,
        terminal_soc_percent=terminal_soc_percent,
        sunrise_soc_min_index=rel_sunrise,
        consumer_continue_on=slot_in.continue_on,
        soc_hold_index=rel_hold,
        soc_hold_percent=(
            options.soc_hold_percent if rel_hold is not None else None
        ),
    )
    commit_slots = _commit_slots_for_buffer(
        options.commit_hours,
        matrix_len=len(setup.matrix),
        remaining_len=len(schedule),
    )
    return schedule[:commit_slots]


def _advance_delivered_and_flex_run(
    setup: _HorizonSetup,
    chart_row: dict,
    mode: int,
    target_power: float,
    delivered_horizon: dict[str, float],
    generic_flex_run: dict[str, dict],
) -> float:
    """Kappt Flex auf das Horizontziel, schreibt den Run-State fort, finalisiert die Energie."""
    _cap_flex_delivery(
        chart_row, setup.consumers_cfg, setup.horizon_limits, delivered_horizon
    )
    for consumer in setup.consumers_cfg:
        power = float(chart_row.get(consumer_column_name(consumer), 0.0) or 0.0)
        update_generic_flex_run_state(generic_flex_run, consumer, power)
    old_soc = float(chart_row["Simulierter SoC (%)"])
    return finalize_chart_row_energy(
        chart_row, mode, target_power, old_soc, setup.battery_params
    )


def _run_horizon_slots(
    setup: _HorizonSetup,
    initial_soc: float,
    on_progress,
    simulation_hour_offset: int | None,
) -> tuple[list[dict], float]:
    """Läuft die Matrix Slot für Slot ab (MPC bzw. Open-Loop-Commit-Puffer)."""
    chart_rows: list[dict] = []
    sim_soc = initial_soc
    total_steps = len(setup.matrix)
    delivered_horizon: dict[str, float] = {c["id"]: 0.0 for c in setup.consumers_cfg}
    generic_flex_run: dict[str, dict] = {}
    commit_buffer: list[dict] = []
    buffer_pos = 0
    own_cbc_collection = not cbc_event_collection_active()
    if own_cbc_collection:
        begin_cbc_event_collection()
    try:
        hour_base = simulation_hour_offset or 0
        for i, row in enumerate(setup.matrix):
            set_cbc_milp_context(simulation_hour_index=hour_base + i)
            slot_in = _slot_solve_inputs(setup, i, delivered_horizon, generic_flex_run)
            if setup.options.commit_hours <= 1:
                sim_soc, chart_row, mode, target_power = _solve_slot_mpc(
                    setup, row, sim_soc, i, slot_in
                )
            else:
                if buffer_pos >= len(commit_buffer):
                    commit_buffer = _refill_commit_buffer(setup, sim_soc, i, slot_in)
                    buffer_pos = 0
                slot = commit_buffer[buffer_pos]
                buffer_pos += 1
                sim_soc, chart_row, mode, target_power = _chart_row_from_schedule_slot(
                    row,
                    sim_soc,
                    setup.battery_params,
                    setup.consumers_cfg,
                    slot,
                )
            sim_soc = _advance_delivered_and_flex_run(
                setup,
                chart_row,
                mode,
                target_power,
                delivered_horizon,
                generic_flex_run,
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
    return chart_rows, sim_soc


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
    options = _HorizonOptions(
        k_push=k_push,
        verbose=verbose,
        commit_hours=commit_hours,
        flex_book_hours=flex_book_hours,
        flex_book_start=flex_book_start,
        sunrise_soc_min_index=sunrise_soc_min_index,
        soc_hold_index=soc_hold_index,
        soc_hold_percent=soc_hold_percent,
    )
    setup = _prepare_horizon_state(
        optimization_matrix,
        initial_soc,
        options,
        battery_params=battery_params,
        consumer_daily_targets_kwh=consumer_daily_targets_kwh,
        charging_contexts=charging_contexts,
        filter_contexts=filter_contexts,
        matrix_prepared=matrix_prepared,
        disable_horizon_soc_anchor=disable_horizon_soc_anchor,
        flexible_consumers=flexible_consumers,
    )
    chart_rows, sim_soc = _run_horizon_slots(
        setup, initial_soc, on_progress, simulation_hour_offset
    )
    if sunrise_soc_min_index is None and not disable_horizon_soc_anchor:
        sim_soc = _apply_forced_grid_recharge_at_horizon_end(
            chart_rows,
            sim_soc,
            battery_params=setup.battery_params,
            horizon_anchor_soc=initial_soc,
        )
    _finalize_chart_rows_for_display(chart_rows, setup.charging_contexts)
    if chart_rows:
        chart_rows[-1]["_horizon_end_soc"] = horizon_end_soc_percent(
            chart_rows,
            initial_soc,
            setup.battery_params,
        )
    return chart_rows


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
    "simulate_baseline_horizon",
    "simulate_baseline_with_optimized_flex",
    "simulate_horizon",
    "simulate_matched_baseline_horizon",
    "sync_chart_row_netzbezug",
    "total_consumption_kwh_from_rows",
]
