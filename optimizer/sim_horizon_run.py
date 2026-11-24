"""Slot loop helpers of ``simulate_horizon``: slot inputs, run state, SoC holds, booking rows.

Split out of ``optimizer.simulation`` (still re-exported there). The functions that call the
MILP (``milp_optimizer`` / ``milp_horizon_schedule``) stay in ``optimizer.simulation``, so tests
keep patching them there.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field

from .cbc_events import (
    begin_cbc_event_collection,
    cbc_event_collection_active,
    clear_cbc_milp_context,
    summarize_cbc_events,
    take_cbc_events,
)
from .charging_context import resolve_charging_contexts
from .generic_flex_run import continue_on_from_state, update_generic_flex_run_state
from .slot_duration import DEFAULT_DT_H
from .targets import consumer_column_name
from .sim_chart_rows import (
    _chart_row_from_schedule_slot,
    attach_ess_soc_columns,
    finalize_chart_row_energy,
)
from .sim_house_batteries import (
    HouseBatteryControl,
    finalize_house_row_energy,
    house_battery_start_socs,
    house_chart_row,
    house_plant_soc,
)
from .sim_horizon_helpers import _cap_flex_delivery, _flex_indices_for_book_hours
from .sim_horizon_types import _HorizonOptions, _HorizonSetup, _SlotInputs
from .sim_horizon_chart_soc import (
    _advance_chart_soc_after_slot,
    _initial_soc_by_ess,
    _seed_virtual_soc_for_chart,
    house_balance_batteries,
    plant_start_soc,
)

# Same logger as before the split (log filters and caplog tests key on it).
logger = logging.getLogger("optimizer.simulation")


def _matrix_and_charging_contexts(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict[str, float] | None,
    charging_contexts: dict[str, dict] | None,
    consumers_cfg: list,
    *,
    matrix_prepared: bool,
) -> tuple[list, dict[str, dict] | None, dict[str, float] | None]:
    """Prepared matrix, charging contexts and daily targets (prepares unless already done)."""
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
    return optimization_matrix, charging_contexts, consumer_daily_targets_kwh


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


def _milp_soc_map(setup: _HorizonSetup, soc_by_house: dict[str, float]) -> dict[str, float] | None:
    """SoC map for a solve inside the run: the start map with the simulated house batteries."""
    if not soc_by_house:
        return setup.current_soc_by_id
    return {**(setup.current_soc_by_id or {}), **soc_by_house}


def _soc_after_hold_slot(options: _HorizonOptions, slot_index: int, sim_soc: float) -> float:
    """SE sunrise carry-in: the book starts at SA₁ with exactly ``soc_hold_percent``.

    The MILP fixes the SoC at the end of ``soc_hold_index``; the slot simulation of
    the unbooked SA₀→SA₁ part can drift from it (control mapping, solver fallback).
    Without this anchor the booked SoC chain gains or loses that drift per window.
    """
    hold = options.soc_hold_percent
    if options.soc_hold_index is None or hold is None or slot_index != options.soc_hold_index:
        return sim_soc
    if abs(float(sim_soc) - float(hold)) > 1.0:
        logger.info(
            "SoC-Hold Slot %d: simuliert %.1f %% statt %.1f %% (MILP-Plan nicht erreicht)",
            slot_index,
            float(sim_soc),
            float(hold),
        )
    return float(hold)


def _cap_flex_and_advance_run(
    setup: _HorizonSetup,
    chart_row: dict,
    delivered_horizon: dict[str, float],
    generic_flex_run: dict[str, dict],
) -> None:
    """Kappt Flex auf das Horizontziel und schreibt den Run-State fort.

    A given plan (``fixed_schedule``) is shown as it is: its solve already held the targets.
    """
    if setup.fixed_schedule:
        _book_flex_delivery(chart_row, setup.consumers_cfg, delivered_horizon)
    else:
        _cap_flex_delivery(
            chart_row, setup.consumers_cfg, setup.horizon_limits, delivered_horizon
        )
    for consumer in setup.consumers_cfg:
        power = float(chart_row.get(consumer_column_name(consumer), 0.0) or 0.0)
        update_generic_flex_run_state(generic_flex_run, consumer, power)


def _book_flex_delivery(
    chart_row: dict, consumers_cfg: list, delivered_horizon: dict[str, float]
) -> None:
    """Books the row's flex energy without a cap (a given plan is shown unchanged)."""
    for consumer in consumers_cfg:
        power = float(chart_row.get(consumer_column_name(consumer), 0.0) or 0.0)
        if power > 0:
            cid = consumer["id"]
            delivered_horizon[cid] = delivered_horizon.get(cid, 0.0) + power * DEFAULT_DT_H


def _slot_limit_marks(slot: dict) -> dict:
    """Import cap limit and cause of a schedule slot (empty when the slot has none)."""
    from .import_cap_report import SLOT_CAUSE_KEY, SLOT_LIMIT_KEY

    if SLOT_LIMIT_KEY not in slot:
        return {}
    return {SLOT_LIMIT_KEY: slot[SLOT_LIMIT_KEY], SLOT_CAUSE_KEY: slot[SLOT_CAUSE_KEY]}


@contextmanager
def _own_cbc_event_collection():
    """Collect CBC events for this run unless an outer collection is already active."""
    own_cbc_collection = not cbc_event_collection_active()
    if own_cbc_collection:
        begin_cbc_event_collection()
    try:
        yield
    finally:
        if own_cbc_collection:
            summary = summarize_cbc_events(take_cbc_events())
            if summary:
                logger.info(summary)
            clear_cbc_milp_context()


_BOOKED_PRICE_FIELDS = ("k_act", "price_buy", "price_source", "k_push_act")
_BOOKED_KW_FIELDS = ("expected_p_act", "expected_p_total", "expected_p_pv")


def _booking_rows(
    raw_plan: list[dict],
    prepared_plan: list[dict],
    booking_matrix: list[dict],
    options: _HorizonOptions,
) -> list[dict]:
    """Prepared plan rows with the actual prices and kW inside the book.

    What the preparation added to the plan's kW (immediate charging, appliance plans, standby
    relief) is added to the actuals too. Slots outside the book are never booked and keep the
    plan's values, so the SoC hold at SA₁ stays reachable.
    """
    if not len(raw_plan) == len(prepared_plan) == len(booking_matrix):
        raise ValueError(
            f"Buchungsmatrix passt nicht zum Plan: {len(booking_matrix)} Zeilen, Plan {len(prepared_plan)}."
        )
    start = options.flex_book_start
    stop = len(prepared_plan) if options.flex_book_hours is None else start + options.flex_book_hours
    rows: list[dict] = []
    for index, (raw, prepared, actual) in enumerate(zip(raw_plan, prepared_plan, booking_matrix)):
        if raw["slot_datetime"] != actual["slot_datetime"]:
            raise ValueError(
                f"Buchungsmatrix Zeile {index}: Slot {actual['slot_datetime']} statt {raw['slot_datetime']}."
            )
        row = dict(prepared)
        if start <= index < stop:
            row.update({key: actual[key] for key in _BOOKED_PRICE_FIELDS if key in actual})
            for key in _BOOKED_KW_FIELDS:
                if key in actual:
                    added = float(prepared[key]) - float(raw[key])
                    row[key] = float(actual[key]) + added if added else actual[key]
        rows.append(row)
    return rows


def _house_soc_after_hold_slot(
    options: _HorizonOptions,
    slot_index: int,
    house: list[dict],
    soc_by_house: dict[str, float],
    planned_soc_by_ess: dict[str, float] | None,
) -> dict[str, float]:
    """``_soc_after_hold_slot`` with several house batteries: the plant SoC is exactly the hold.

    Each battery takes its planned SoC (its own SoC when the slot has no plan per battery); all
    are then shifted by the same SoC difference, which moves the plant SoC by exactly that much.
    """
    hold = options.soc_hold_percent
    if options.soc_hold_index is None or hold is None or slot_index != options.soc_hold_index:
        return soc_by_house
    simulated = house_plant_soc(house, soc_by_house)
    if abs(simulated - float(hold)) > 1.0:
        logger.info(
            "SoC-Hold Slot %d: simuliert %.1f %% statt %.1f %% (MILP-Plan nicht erreicht)",
            slot_index,
            simulated,
            float(hold),
        )
    base = {
        ess_id: float((planned_soc_by_ess or {}).get(ess_id, soc))
        for ess_id, soc in soc_by_house.items()
    }
    shift = float(hold) - house_plant_soc(house, base)
    return {ess_id: soc + shift for ess_id, soc in base.items()}


def _single_battery_soc_map(setup: _HorizonSetup, sim_soc: float) -> dict[str, float]:
    """Simulated SoC of a single house battery for a refill solve (empty without a start map).

    The MILP takes a single battery's start SoC from ``current_soc_by_id`` when it is there, so
    a refill inside the matrix has to find the simulated SoC in the map, not the run's start.
    """
    by_id = setup.current_soc_by_id or {}
    house = house_balance_batteries(setup.batteries)
    if len(house) != 1:
        return {}
    ess_id = str(house[0].get("id") or "ess_0").strip() or "ess_0"
    return {ess_id: float(sim_soc)} if ess_id in by_id else {}


@dataclass
class _RunState:
    """State that ``_run_horizon_slots`` carries from slot to slot."""

    house: list[dict]
    several: bool
    soc_by_house: dict[str, float]
    sim_soc: float
    soc_by_ess: dict
    virtual_entries: object
    chart_entities: list
    delivered_horizon: dict[str, float]
    generic_flex_run: dict[str, dict] = field(default_factory=dict)
    commit_buffer: list[dict] = field(default_factory=list)
    buffer_pos: int = 0


@dataclass
class _SlotOutcome:
    """Chart row of one slot and what its finish needs (house controls or battery command)."""

    chart_row: dict
    controls: tuple[HouseBatteryControl, ...] = ()
    planned_by: dict[str, float] | None = None
    slot: dict | None = None
    mode: int | None = None
    target_power: float | None = None


def _init_run_state(setup: _HorizonSetup, initial_soc: float) -> _RunState:
    """Start state of the slot loop (several house batteries: one SoC per battery)."""
    house = house_balance_batteries(setup.batteries)
    several = len(house) > 1
    soc_by_house = (
        house_battery_start_socs(house, setup.current_soc_by_id) if several else {}
    )
    sim_soc = plant_start_soc(setup.batteries, initial_soc, setup.current_soc_by_id)
    soc_by_ess = _initial_soc_by_ess(setup, initial_soc)
    virtual_entries = _seed_virtual_soc_for_chart(setup, soc_by_ess)
    return _RunState(
        house=house,
        several=several,
        soc_by_house=soc_by_house,
        sim_soc=sim_soc,
        soc_by_ess=soc_by_ess,
        virtual_entries=virtual_entries,
        chart_entities=list(setup.chart_soc_entities) or list(setup.batteries),
        delivered_horizon={c["id"]: 0.0 for c in setup.consumers_cfg},
    )


def _commit_slot_outcome(
    setup: _HorizonSetup, state: _RunState, booked_row: dict, slot: dict
) -> _SlotOutcome:
    """Chart row of a committed open-loop schedule slot (applied to the booked row)."""
    if state.several:
        planned_by = slot.get("planned_soc_by_ess")
        chart_row, controls = house_chart_row(
            booked_row,
            state.soc_by_house,
            state.house,
            setup.battery_params,
            setup.consumers_cfg,
            slot["milp_plan"],
            planned_by,
            dict(slot.get("consumer_powers") or {}),
            dict(slot.get("consumer_pv_follow") or {}),
        )
        chart_row.update(_slot_limit_marks(slot))
        return _SlotOutcome(chart_row, controls, planned_by, slot=slot)
    state.sim_soc, chart_row, mode, target_power = _chart_row_from_schedule_slot(
        booked_row,
        state.sim_soc,
        setup.battery_params,
        setup.consumers_cfg,
        slot,
    )
    return _SlotOutcome(chart_row, slot=slot, mode=mode, target_power=target_power)


def _finish_run_slot(
    setup: _HorizonSetup, state: _RunState, outcome: _SlotOutcome, slot_index: int
) -> None:
    """Books the slot's energy, advances the SoC (per house battery) and the chart SoC maps."""
    chart_row = outcome.chart_row
    # Attach start-of-slot per-ESS SoC (same timing as COL_SOC), then finalize
    # end-of-slot plant SoC, then advance maps for the next attach. Writing
    # COL_SOC (start) back into soc_by_ess lagged house columns by one slot
    # vs aggregate / Steuerbefehl underlay.
    attach_ess_soc_columns(chart_row, state.soc_by_ess, state.chart_entities)
    _cap_flex_and_advance_run(
        setup, chart_row, state.delivered_horizon, state.generic_flex_run
    )
    if state.several:
        soc_by_house = finalize_house_row_energy(
            chart_row, outcome.controls, state.house, state.soc_by_house
        )
        state.soc_by_house = _house_soc_after_hold_slot(
            setup.options, slot_index, state.house, soc_by_house, outcome.planned_by
        )
        state.sim_soc = house_plant_soc(state.house, state.soc_by_house)
    else:
        old_soc = float(chart_row["Simulierter SoC (%)"])
        sim_soc = finalize_chart_row_energy(
            chart_row, outcome.mode, outcome.target_power, old_soc, setup.battery_params
        )
        state.sim_soc = _soc_after_hold_slot(setup.options, slot_index, sim_soc)
    _advance_chart_soc_after_slot(
        setup,
        chart_row,
        state.soc_by_ess,
        slot=outcome.slot,
        slot_index=slot_index,
        virtual_entries=state.virtual_entries,
        end_soc=state.sim_soc,
        house_soc=state.soc_by_house if state.several else None,
    )
