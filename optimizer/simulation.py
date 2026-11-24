"""Horizont-Simulation (optimiert, Baseline) und Kostenberechnung.

Import facade: the slot loop lives in ``optimizer.sim_horizon_run`` and is re-exported here.
The MILP callers (``milp_optimizer``, ``milp_horizon_schedule``, ``simulate_horizon`` ...) stay
patch points on this module; patch any other moved name in ``optimizer.sim_horizon_run``
(see ``.cursor/rules/import-facades.mdc``).
"""
from __future__ import annotations

import logging
from dataclasses import replace

import config
from . import battery as bat
from .cbc_events import set_cbc_milp_context
from .charging_context import (  # noqa: F401  (consumer_charging_eligible_indices: sim_baseline facade)
    apply_horizon_charging_limits,
    consumer_charging_eligible_indices,
    resolve_charging_contexts,
)
from .filter_context import adjust_targets_for_native_filter, resolve_filter_contexts
from .fixed_load import adjust_targets_for_continuous_load
from .import_cap_report import first_slot_mark
from .import_power_limit import ImportCaps
from .milp import milp_horizon_schedule, milp_optimizer
from .targets import resolve_horizon_consumer_targets_kwh
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
from .sim_house_batteries import HouseBatteryControl, house_chart_row, house_plant_soc
from .sim_horizon_helpers import (
    _apply_forced_grid_recharge_at_horizon_end,
    _cap_flex_delivery,
    _commit_slots_for_buffer,
    _flex_indices_for_book_hours,
    _relative_sunrise_index,
    _terminal_soc_for_commit,
)
from optimizer.sim_horizon_types import (  # noqa: F401  (re-exported)
    _HorizonOptions,
    _HorizonSetup,
    _SlotInputs,
)
from optimizer.sim_horizon_chart_soc import (  # noqa: F401  (re-exported)
    _advance_chart_soc_after_slot,
    _initial_soc_by_ess,
    _resolve_chart_soc_entities,
    _resolve_horizon_batteries,
    house_balance_batteries,
    plant_start_soc,
    _resolve_standby_chart_plans,
    _seed_virtual_soc_for_chart,
)
from .sim_horizon_run import (  # noqa: F401  (re-exported)
    _BOOKED_KW_FIELDS,
    _BOOKED_PRICE_FIELDS,
    _RunState,
    _SlotOutcome,
    _booking_rows,
    _cap_flex_and_advance_run,
    _commit_slot_outcome,
    _finish_run_slot,
    _house_soc_after_hold_slot,
    _init_run_state,
    _matrix_and_charging_contexts,
    _milp_soc_map,
    _own_cbc_event_collection,
    _single_battery_soc_map,
    _slot_limit_marks,
    _slot_solve_inputs,
    _soc_after_hold_slot,
)

logger = logging.getLogger(__name__)


def _consumers_or_configured(flexible_consumers: list | None) -> list:
    """The given consumers, an empty list included; the configured ones only for ``None``."""
    if flexible_consumers is not None:
        return flexible_consumers
    return config.get_flexible_consumers(optimizer_only=True)


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
    import_caps: ImportCaps | None = None,
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
    consumers_cfg = _consumers_or_configured(flexible_consumers)
    mode, target_power, target_soc, consumer_powers, consumer_pv_follow, plan, _ = milp_optimizer(
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
        import_caps=import_caps,
    )
    result = _chart_row_from_controls(
        row,
        sim_soc,
        battery_params,
        consumers_cfg,
        mode,
        target_power,
        consumer_powers,
        consumer_pv_follow,
        automatik_discharge_cap_kw=bat.import_cap_discharge_cap_kw(
            plan, row, sum(consumer_powers.values()), battery_params
        ),
    )
    mark = first_slot_mark(plan, import_caps) if import_caps is not None else None
    if mark is not None:
        result[1].update(mark)
    return result


def _prepare_horizon_state(
    optimization_matrix: list,
    initial_soc: float,
    options: _HorizonOptions,
    *,
    battery_params: dict | list[dict] | None,
    consumer_daily_targets_kwh: dict[str, float] | None,
    charging_contexts: dict[str, dict] | None,
    filter_contexts: dict[str, dict] | None,
    matrix_prepared: bool,
    disable_horizon_soc_anchor: bool,
    flexible_consumers: list | None,
    current_soc_by_id: dict[str, float] | None = None,
    fixed_schedule: bool = False,
) -> _HorizonSetup:
    """Bereitet Matrix, Lade-/Filterkontexte, Flex-Horizontgrenzen und Terminal-SoC auf.

    ``fixed_schedule``: the matrix is the control solve's, with the standby relief already in
    it; the standby plans are only resolved for the chart's pack SoC.
    """
    consumers_cfg = _consumers_or_configured(flexible_consumers)
    optimization_matrix, charging_contexts, consumer_daily_targets_kwh = (
        _matrix_and_charging_contexts(
            optimization_matrix,
            consumer_daily_targets_kwh,
            charging_contexts,
            consumers_cfg,
            matrix_prepared=matrix_prepared,
        )
    )
    batteries, agg_battery = _resolve_horizon_batteries(battery_params)
    chart_entities = _resolve_chart_soc_entities(batteries)
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
    # SE sunrise: the target belongs to the book window, so only native runs
    # inside it are credited (the SA₀→SA₁ run is booked by the previous window).
    credit_indices = (
        _flex_indices_for_book_hours(
            len(optimization_matrix), 0, options.flex_book_hours, options.flex_book_start
        )
        if options.flex_book_hours is not None
        else None
    )
    horizon_limits = adjust_targets_for_native_filter(
        horizon_limits, consumers_cfg, optimization_matrix, filters, credit_indices
    )
    # Continuous loads are booked as fixed load over the same slots (SE matrix);
    # Live targets of such consumers are 0, so nothing changes there.
    horizon_limits = adjust_targets_for_continuous_load(
        horizon_limits,
        consumers_cfg,
        len(credit_indices) if credit_indices is not None else len(optimization_matrix),
    )
    if disable_horizon_soc_anchor:
        horizon_terminal_soc = None
    else:
        # The MILP terminal anchor binds all house batteries: it needs the plant SoC.
        horizon_terminal_soc = (
            None
            if options.sunrise_soc_min_index is not None
            else plant_start_soc(batteries, initial_soc, current_soc_by_id)
        )
    standby_plans, standby_packs_by_id = _resolve_standby_chart_plans(
        optimization_matrix, current_soc_by_id
    )
    matrix = optimization_matrix
    if standby_plans and not fixed_schedule:
        from optimizer.powerstation_standby import apply_standby_load_relief

        # Island relief + grid-pass-through charge must hit house MILP / Chart1
        # energy balance (same as main.py live path).
        matrix = apply_standby_load_relief(optimization_matrix, standby_plans)
    return _HorizonSetup(
        matrix=matrix,
        consumers_cfg=consumers_cfg,
        battery_params=agg_battery,
        batteries=batteries,
        charging_contexts=charging_contexts,
        filters=filters,
        horizon_limits=horizon_limits,
        horizon_terminal_soc=horizon_terminal_soc,
        options=options,
        current_soc_by_id=current_soc_by_id,
        chart_soc_entities=chart_entities,
        standby_plans=standby_plans,
        standby_packs_by_id=standby_packs_by_id,
        fixed_schedule=fixed_schedule,
    )


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
        import_caps=options.import_caps_from(hour_index),
    )


def _solve_slot_mpc_house(
    setup: _HorizonSetup,
    house: list[dict],
    row: dict,
    soc_by_house: dict[str, float],
    hour_index: int,
    slot_in: _SlotInputs,
) -> tuple[dict, tuple[HouseBatteryControl, ...], dict[str, float] | None]:
    """Slot re-solve with several house batteries: the MILP plans each from its simulated SoC."""
    options = setup.options
    rel_sunrise = _relative_sunrise_index(
        options.sunrise_soc_min_index, hour_index, len(slot_in.remaining_slice)
    )
    rel_hold = _relative_sunrise_index(
        options.soc_hold_index, hour_index, len(slot_in.remaining_slice)
    )
    import_caps = options.import_caps_from(hour_index)
    _, _, _, consumer_powers, consumer_pv_follow, plan, _ = milp_optimizer(
        slot_in.remaining_slice,
        row["hour"],
        house_plant_soc(house, soc_by_house),
        battery_params=setup.batteries,
        k_push=options.k_push,
        verbose=options.verbose,
        consumers=setup.consumers_cfg,
        consumer_remaining_kwh=slot_in.remaining,
        spa_remaining_kwh=None,
        flex_indices=slot_in.flex_indices,
        charging_contexts=setup.charging_contexts,
        filter_contexts=setup.filters,
        terminal_soc_percent=_terminal_soc_for_commit(
            options.commit_hours, len(slot_in.remaining_slice), setup.horizon_terminal_soc
        ),
        sunrise_soc_min_index=rel_sunrise,
        consumer_continue_on=slot_in.continue_on,
        soc_hold_index=rel_hold,
        soc_hold_percent=options.soc_hold_percent if rel_hold is not None else None,
        current_soc_by_id=_milp_soc_map(setup, soc_by_house),
        import_caps=import_caps,
    )
    planned_by = plan.get("planned_soc_by_ess")
    chart_row, controls = house_chart_row(
        row,
        soc_by_house,
        house,
        setup.battery_params,
        setup.consumers_cfg,
        plan,
        planned_by,
        consumer_powers,
        consumer_pv_follow,
    )
    mark = first_slot_mark(plan, import_caps) if import_caps is not None else None
    if mark is not None:
        chart_row.update(mark)
    return chart_row, controls, planned_by


def _refill_commit_buffer(
    setup: _HorizonSetup,
    sim_soc: float,
    hour_index: int,
    slot_in: _SlotInputs,
    soc_by_house: dict[str, float],
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
    milp_batteries = setup.batteries or setup.battery_params
    schedule = milp_horizon_schedule(
        remaining_slice,
        sim_soc,
        battery_params=milp_batteries,
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
        # The simulated SoC, not the run's start map (a refill starts inside the matrix).
        current_soc_by_id=_milp_soc_map(setup, soc_by_house),
        import_caps=options.import_caps_from(hour_index),
    )
    commit_slots = _commit_slots_for_buffer(
        options.commit_hours,
        matrix_len=len(setup.matrix),
        remaining_len=len(schedule),
    )
    return schedule[:commit_slots]


def _solve_run_slot(
    setup: _HorizonSetup,
    state: _RunState,
    row: dict,
    hour_index: int,
    slot_in: _SlotInputs,
) -> _SlotOutcome:
    """Chart row of one slot: MPC re-solve (``commit_hours=1``) or the next committed slot."""
    if setup.options.commit_hours <= 1 and state.several:
        chart_row, controls, planned_by = _solve_slot_mpc_house(
            setup, state.house, row, state.soc_by_house, hour_index, slot_in
        )
        return _SlotOutcome(chart_row, controls, planned_by)
    if setup.options.commit_hours <= 1:
        state.sim_soc, chart_row, mode, target_power = _solve_slot_mpc(
            setup, row, state.sim_soc, hour_index, slot_in
        )
        return _SlotOutcome(chart_row, mode=mode, target_power=target_power)
    if state.buffer_pos >= len(state.commit_buffer):
        if setup.fixed_schedule:
            raise RuntimeError(
                f"Gegebener Plan endet vor Slot {hour_index} (kein Ersatz-Solve)."
            )
        state.commit_buffer = _refill_commit_buffer(
            setup,
            state.sim_soc,
            hour_index,
            slot_in,
            state.soc_by_house
            if state.several
            else _single_battery_soc_map(setup, state.sim_soc),
        )
        state.buffer_pos = 0
    slot = state.commit_buffer[state.buffer_pos]
    state.buffer_pos += 1
    booked_row = (
        setup.booking_matrix[hour_index] if setup.booking_matrix is not None else row
    )
    return _commit_slot_outcome(setup, state, booked_row, slot)


def _run_horizon_slots(
    setup: _HorizonSetup,
    initial_soc: float,
    on_progress,
    simulation_hour_offset: int | None,
    horizon_schedule: list[dict] | None = None,
) -> tuple[list[dict], float]:
    """Läuft die Matrix Slot für Slot ab (MPC bzw. Open-Loop-Commit-Puffer).

    With several house batteries every slot steps each battery (``sim_house_batteries``) and
    ``sim_soc`` is their plant SoC. ``horizon_schedule`` fills the commit buffer once; it is
    never refilled by a solve.
    """
    chart_rows: list[dict] = []
    state = _init_run_state(setup, initial_soc)
    if horizon_schedule is not None:
        state.commit_buffer = list(horizon_schedule[: len(setup.matrix)])
    total_steps = len(setup.matrix)
    with _own_cbc_event_collection():
        hour_base = simulation_hour_offset or 0
        for i, row in enumerate(setup.matrix):
            set_cbc_milp_context(simulation_hour_index=hour_base + i)
            slot_in = _slot_solve_inputs(
                setup, i, state.delivered_horizon, state.generic_flex_run
            )
            outcome = _solve_run_slot(setup, state, row, i, slot_in)
            _finish_run_slot(setup, state, outcome, i)
            chart_rows.append(outcome.chart_row)
            if on_progress is not None:
                on_progress(i + 1, total_steps)
    return chart_rows, state.sim_soc


def _validate_horizon_schedule(
    horizon_schedule: list[dict],
    optimization_matrix: list,
    commit_hours: int,
    booking_matrix: list | None,
) -> None:
    """A given plan must cover the matrix; it runs open-loop and never on SE booking rows."""
    if commit_hours <= 1:
        raise ValueError("horizon_schedule erfordert den Open-Loop-Pfad (commit_hours > 1).")
    if booking_matrix is not None:
        raise ValueError("horizon_schedule und booking_matrix schließen sich aus.")
    if len(horizon_schedule) < len(optimization_matrix):
        raise ValueError(
            f"horizon_schedule hat {len(horizon_schedule)} Slots, die Matrix "
            f"{len(optimization_matrix)} (kein Ersatz-Solve für den Rest)."
        )


def simulate_horizon(
    optimization_matrix: list,
    initial_soc: float,
    battery_params: dict | list[dict] | None = None,
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
    current_soc_by_id: dict[str, float] | None = None,
    booking_matrix: list | None = None,
    import_caps: ImportCaps | None = None,
    horizon_schedule: list[dict] | None = None,
) -> list:
    """
    Simuliert einen Optimierungshorizont über die gesamte Matrix.

    commit_hours=1: re-solve every matrix slot (Live MPC).
    Several house batteries: the run keeps a SoC per house battery in both paths
    (``sim_house_batteries``); the SoC column is the plant SoC.
    commit_hours=N (N>1): wall-clock hours → commit N/dt_h QH slots open-loop (SE).
    disable_horizon_soc_anchor: keine Terminal-/Sonnenaufgangs-SOC_min-Gleichheit.
    flex_book_hours / flex_book_start: Flex nur in Absolutstunden
    [flex_book_start, flex_book_start + flex_book_hours).
    soc_hold_*: optional hard SoC equality (SE SA₁ carry-in); survives disable_horizon_soc_anchor.
    booking_matrix: SE forecast mode, the MILP plans on ``optimization_matrix`` and the schedule
    is applied to these actual rows (open-loop only; ``docs/dev/se-forecast-mode.md``).
    import_caps: SE import limit per matrix slot. A re-solve inside the matrix keeps these limits
    and does not lift them by what it already booked (``docs/dev/max-power-tariff-plan.md``, P4).
    horizon_schedule: Live Chart 1, the control solve's plan (``milp_plan["horizon_schedule"]``)
    on its own prepared matrix. The run applies it slot by slot and never solves: no refill, no
    flex cap, no forced grid recharge at the horizon end, no second standby relief. A plan
    shorter than the matrix raises ``ValueError``.
    """
    if horizon_schedule is not None:
        _validate_horizon_schedule(
            horizon_schedule, optimization_matrix, commit_hours, booking_matrix
        )
    if commit_hours < 1:
        raise ValueError(
            f"commit_hours must be >= 1 (got {commit_hours}). "
            "Use 1 for per-slot re-opt or len(matrix) for open-loop."
        )
    if booking_matrix is not None and commit_hours <= 1:
        raise ValueError("booking_matrix erfordert den Open-Loop-Pfad (commit_hours > 1).")
    if disable_horizon_soc_anchor:
        sunrise_soc_min_index = None
    raw_plan = [dict(row) for row in optimization_matrix] if booking_matrix is not None else None
    options = _HorizonOptions(
        k_push=k_push,
        verbose=verbose,
        commit_hours=commit_hours,
        flex_book_hours=flex_book_hours,
        flex_book_start=flex_book_start,
        sunrise_soc_min_index=sunrise_soc_min_index,
        soc_hold_index=soc_hold_index,
        soc_hold_percent=soc_hold_percent,
        import_caps=import_caps,
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
        current_soc_by_id=current_soc_by_id,
        fixed_schedule=horizon_schedule is not None,
    )
    if booking_matrix is not None:
        setup = replace(
            setup,
            booking_matrix=_booking_rows(raw_plan, setup.matrix, booking_matrix, options),
        )
    chart_rows, sim_soc = _run_horizon_slots(
        setup, initial_soc, on_progress, simulation_hour_offset, horizon_schedule
    )
    plant_initial_soc = plant_start_soc(setup.batteries, initial_soc, setup.current_soc_by_id)
    if (
        sunrise_soc_min_index is None
        and not disable_horizon_soc_anchor
        and horizon_schedule is None
    ):
        sim_soc = _apply_forced_grid_recharge_at_horizon_end(
            chart_rows,
            sim_soc,
            battery_params=setup.battery_params,
            horizon_anchor_soc=plant_initial_soc,
        )
    _finalize_chart_rows_for_display(chart_rows, setup.charging_contexts)
    if chart_rows and len(house_balance_batteries(setup.batteries)) > 1:
        # Several house batteries: the end is their simulated plant SoC (the plant battery
        # booked from the last row's start would not match the batteries' own limits).
        chart_rows[-1]["_horizon_end_soc"] = round(float(sim_soc), 1)
    elif chart_rows:
        chart_rows[-1]["_horizon_end_soc"] = horizon_end_soc_percent(
            chart_rows,
            plant_initial_soc,
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
