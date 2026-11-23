"""MILP build and solve: horizon model with objective, flex side and SoC anchor constraints.

Split out of ``optimizer.milp`` (still re-exported there). ``milp_optimizer`` and
``milp_horizon_schedule`` call ``_solve_milp_to_model`` through ``optimizer.milp``.
"""
from __future__ import annotations

import logging
from typing import Any

import config
from . import battery as bat
from .cbc_events import record_cbc_event, update_cbc_milp_context_from_row
from .cbc_solver import solve_with_strict_fallback
from .slot_duration import DEFAULT_DT_H
from .thermal_flex_context import add_thermal_flex_constraints
from .milp_inputs import (
    _MilpInputs,
    _prepare_milp_inputs,
    _resolve_thermal_flex_contexts,
)
from .milp_consumers import (
    _add_consumer_delivery_constraints,
    add_generic_flex_rolling_constraints,
    block_flex_outside_book,
)
from .milp_horizon import (
    MilpHorizonModel,
    _add_milp_objective,
    _add_pv_only_charge_through_sunrise,
    _add_soc_equality_constraint,
    _add_terminal_soc_constraint,
    _build_milp_model,
    _terminal_soc_energy_kwh,
    plant_soc_view,
)
from .milp_horizon_extras import BASE_LEVEL_ENV, base_level_enabled, plant_capacity_kwh
from .import_power_limit import ImportCaps
from .milp_ev_pool import add_ev_pool_constraints
from .milp_import_cap import add_import_cap_constraints
from .milp_vendor_mode import add_vendor_mode_export_constraints, plan_vendor_mode_enabled
from .milp_defaults import (
    _default_inverter_params,
    _default_pv_systems,
    _primary_battery_params,
)

# Same logger as before the split (log filters and caplog tests key on it).
logger = logging.getLogger("optimizer.milp")


def _base_level_start(
    model: MilpHorizonModel,
    current_soc: float,
    current_soc_by_id: dict[str, float] | None,
    soc_hold_index: int | None,
    soc_hold_percent: float | None,
) -> tuple[int, float] | None:
    """First slot the SoC base level tracks and the plant energy before it (``None`` when off).

    The energy is that of all house batteries in the model, like the base level's target and held
    energy. With a SoC hold the plan starts for real after the hold: the slots before it are not
    replayed and only lead there; the hold percent is a plant SoC (``plant_capacity_kwh``). Without
    a hold one battery starts at ``current_soc``; several need each one's SoC in
    ``current_soc_by_id`` (``ValueError`` otherwise).
    """
    if not base_level_enabled():
        return None
    if soc_hold_index is not None and soc_hold_percent is not None:
        return soc_hold_index + 1, float(soc_hold_percent) / 100.0 * plant_capacity_kwh(model)
    ess_ids = list(model.ess_ids)
    params_by_id = model.battery_params_by_id
    if len(ess_ids) == 1:
        capacity = float(params_by_id[ess_ids[0]].get("battery_capacity_kwh") or 0.0)
        return 0, float(current_soc) / 100.0 * capacity
    by_id = current_soc_by_id or {}
    missing = [eid for eid in ess_ids if eid not in by_id]
    if missing:
        raise ValueError(
            f"{BASE_LEVEL_ENV}: Start-SoC fehlt für Hausbatterie(n) {missing} (vorhanden: {sorted(by_id)})."
        )
    return 0, sum(
        float(by_id[eid]) / 100.0 * float(params_by_id[eid].get("battery_capacity_kwh") or 0.0)
        for eid in ess_ids
    )


def _wear_cent_per_kwh_by_ess(model: MilpHorizonModel) -> dict[str, float]:
    """Wear [ct/kWh throughput] of each house battery in the model, from its own ``battery_wear``.

    Battery params from the house config carry ``battery_wear`` (``battery_params_from_planning``).
    A single battery without the key (legacy flat params) takes the live scenario's wear, as
    before. With several batteries each needs its own: one battery's wear does not price another.
    """
    from .battery_wear import battery_wear_cent_per_kwh_from_config

    ess_ids = list(model.ess_ids or [])
    params_by_id = model.battery_params_by_id or {}
    out: dict[str, float] = {}
    for eid in ess_ids:
        bat = params_by_id[eid]
        capacity = float(bat.get("battery_capacity_kwh") or 0.0)
        if capacity <= 0.0:
            out[eid] = 0.0
        elif "battery_wear" in bat:
            out[eid] = battery_wear_cent_per_kwh_from_config(bat["battery_wear"], capacity)
        elif len(ess_ids) == 1:
            out[eid] = config.get_battery_wear_cent_per_kwh(capacity)
        else:
            raise ValueError(
                f"Batterie '{eid}': battery_wear fehlt in den Speicherparametern; mit mehreren "
                f"Hausbatterien braucht jede ihren eigenen Verschleiß ({ess_ids})."
            )
    return out


def _build_milp_model_with_objective(
    matrix: list[dict[str, Any]],
    battery_params: dict | list[dict],
    current_soc: float,
    k_push: float,
    inputs: _MilpInputs,
    consumer_continue_on: dict[str, bool] | None,
    *,
    hk_max_export_kw: float | None = None,
    inbound_export_limit_kw: float | None = None,
    export_caps_kw: list[float | None] | None = None,
    current_soc_by_id: dict[str, float] | None = None,
    inverter_params: dict | list[dict] | None = None,
    pv_systems: list[dict] | None = None,
    soc_hold_index: int | None = None,
    soc_hold_percent: float | None = None,
) -> MilpHorizonModel:
    """Horizontmodell samt Zielfunktion (Energiekosten + Batterie-Verschleiß)."""
    from .export_power_limit import export_caps_for_horizon

    caps = export_caps_kw
    if caps is None:
        caps = export_caps_for_horizon(
            matrix[: inputs.horizon],
            hk_max_export_kw=hk_max_export_kw,
            inbound_limit_kw=inbound_export_limit_kw,
            fallback_k_push=k_push,
        )
    inv = (
        inverter_params
        if inverter_params is not None
        else _default_inverter_params()
    )
    pvs = pv_systems if pv_systems is not None else _default_pv_systems()
    model = _build_milp_model(
        matrix,
        inputs.horizon,
        battery_params,
        current_soc,
        inputs.milp_consumers,
        inputs.fixed_flex_by_t,
        inputs.remaining,
        inputs.ev_milp_by_id,
        consumer_continue_on=consumer_continue_on,
        dt_h=inputs.dt_h,
        export_caps_kw=caps,
        current_soc_by_id=current_soc_by_id,
        inverter_params=inv,
        pv_systems=pvs,
    )
    _add_milp_objective(
        model,
        matrix,
        k_push,
        inputs.ev_milp_by_id,
        wear_cent_per_kwh=0.0,
        wear_cent_per_kwh_by_ess=_wear_cent_per_kwh_by_ess(model),
        base_level_start=_base_level_start(
            model, current_soc, current_soc_by_id, soc_hold_index, soc_hold_percent
        ),
    )
    return model


def _add_flex_side_constraints(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    inputs: _MilpInputs,
    verbose: bool,
    consumer_continue_on: dict[str, bool] | None,
    thermal_flex_contexts: dict[str, dict] | None,
) -> None:
    """Liefermengen, generische Flex-Rollfenster und thermische Randbedingungen."""
    block_flex_outside_book(model, inputs.book_indices)
    _add_consumer_delivery_constraints(
        model,
        matrix,
        inputs.remaining,
        inputs.schedule_indices,
        inputs.contexts,
        verbose,
        filter_contexts=inputs.filters,
        book_indices=inputs.book_indices,
    )
    add_generic_flex_rolling_constraints(
        model,
        matrix,
        inputs.schedule_indices,
        inputs.contexts,
        consumer_continue_on,
        filter_contexts=inputs.filters,
    )
    add_ev_pool_constraints(model)
    window = matrix[: inputs.horizon]
    thermal_contexts = _resolve_thermal_flex_contexts(
        window, inputs.active, thermal_flex_contexts
    )
    add_thermal_flex_constraints(
        model,
        window,
        inputs.schedule_indices,
        thermal_contexts,
        consumer_continue_on=consumer_continue_on,
    )
    from optimizer.thermal_flex_context import LIVE_STORE_PLAN_KEY

    model.live_store_plans = {
        str(cid): ctx[LIVE_STORE_PLAN_KEY]
        for cid, ctx in thermal_contexts.items()
        if isinstance(ctx, dict) and ctx.get(LIVE_STORE_PLAN_KEY) is not None
    }


def _reserve_build_before(model: MilpHorizonModel, sunrise_index: int) -> float:
    """kWh the reserve floor (Reserve P2) needs above the start energy up to ``sunrise_index``.

    Positive: the reserve has to be built (or held against the idle drain) before sunrise, so
    the PV-only anchor would make the plan infeasible.
    """
    floors = model.reserve_floor_kwh
    if not floors or model.reserve_start_kwh is None:
        return 0.0
    last = min(int(sunrise_index), len(floors) - 1)
    if last < 0:
        return 0.0
    # The idle drain lowers the start energy slot by slot (Reserve P4).
    params = model.battery_params_by_id[model.ess_ids[0]]
    base_kwh = bat.idle_drain_floor_soc(params) / 100.0 * float(params["battery_capacity_kwh"])
    drain_kwh = bat.idle_drain_kw(params) * model.dt_h
    start = float(model.reserve_start_kwh)
    return max(
        (
            floors[k] - (start - drain_kwh * (k + 1))
            for k in range(last + 1)
            if floors[k] > base_kwh + 1e-9
        ),
        default=0.0,
    )


def _add_soc_anchor_constraints(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    battery_params: dict | list[dict],
    current_soc: float,
    verbose: bool,
    *,
    soc_hold_index: int | None,
    soc_hold_percent: float | None,
    sunrise_soc_min_index: int | None,
    terminal_soc_percent: float | None,
) -> None:
    """SOC-Anker in Vorrangfolge: Hold-Slot, PV-only bis Sonnenaufgang, End-SoC.

    ``soc_hold_percent`` and ``terminal_soc_percent`` are plant SoC values: they bind the energy
    of all house batteries (``plant_capacity_kwh``), not the first battery alone.
    """
    battery_params = _primary_battery_params(battery_params)
    # The sunrise check compares the plan's SoC: the plant's with several house batteries.
    current_soc, soc_params = plant_soc_view(model, current_soc, battery_params)
    if soc_hold_index is not None and soc_hold_percent is not None:
        e_hold = (float(soc_hold_percent) / 100.0) * plant_capacity_kwh(model)
        _add_soc_equality_constraint(model, soc_hold_index, e_hold)
        if verbose:
            logger.info(
                "MILP SOC-Hold: Slot %d = %.1f %%",
                soc_hold_index,
                float(soc_hold_percent),
            )
    elif sunrise_soc_min_index is not None:
        # Floor already via e_batt lowBound; do not force == SOC_min (residual dump).
        min_soc = float(soc_params["min_soc"])
        below_min = float(current_soc) < min_soc - 1e-9
        reserve_build_kwh = _reserve_build_before(model, sunrise_soc_min_index)
        if below_min:
            # Plant already below SOC_min: PV-only would block grid recovery before
            # sunrise and make the whole MILP Infeasible (empty EV/flex plan).
            if verbose:
                logger.warning(
                    "MILP SOC-Anker Sonnenaufgang: Slot %d — SoC %.1f%% < min %.1f%%; "
                    "skip PV-only so grid can recover to SOC_min",
                    sunrise_soc_min_index,
                    float(current_soc),
                    min_soc,
                )
        elif reserve_build_kwh > 1e-9:
            # Building the virtual reserve may need grid-side p_charge before sunrise;
            # PV-only would make that hard constraint Infeasible → Automatik fallback.
            if verbose:
                logger.warning(
                    "MILP SOC-Anker Sonnenaufgang: Slot %d — virtual reserve floor needs "
                    "%.3f kWh more before it; skip PV-only so grid can build the reserve",
                    sunrise_soc_min_index,
                    reserve_build_kwh,
                )
        else:
            _add_pv_only_charge_through_sunrise(model, matrix, sunrise_soc_min_index)
            if verbose:
                logger.info(
                    "MILP SOC-Anker Sonnenaufgang: Slot %d PV-only charge (no hard SOC_min eq)",
                    sunrise_soc_min_index,
                )
    elif e_terminal := _terminal_soc_energy_kwh(model, terminal_soc_percent):
        _add_terminal_soc_constraint(model, e_terminal)
        if verbose:
            logger.info(
                "MILP End-SoC-Randbedingung: %.1f %% (aktuell %.1f %%)",
                terminal_soc_percent,
                current_soc,
            )


def _solve_milp_to_model(
    matrix: list[dict[str, Any]],
    current_soc: float,
    battery_params: dict | list[dict],
    k_push: float,
    verbose: bool,
    consumers: list | None,
    consumer_remaining_kwh: dict[str, float] | None,
    spa_remaining_kwh: float | None,
    flex_indices: list[int] | None,
    charging_contexts: dict[str, dict] | None,
    filter_contexts: dict[str, dict] | None,
    terminal_soc_percent: float | None,
    sunrise_soc_min_index: int | None,
    consumer_continue_on: dict[str, bool] | None,
    thermal_flex_contexts: dict[str, dict] | None,
    soc_hold_index: int | None = None,
    soc_hold_percent: float | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
    hk_max_export_kw: float | None = None,
    inbound_export_limit_kw: float | None = None,
    export_caps_kw: list[float | None] | None = None,
    current_soc_by_id: dict[str, float] | None = None,
    inverter_params: dict | list[dict] | None = None,
    pv_systems: list[dict] | None = None,
    import_caps: ImportCaps | None = None,
) -> tuple[MilpHorizonModel, dict[str, float], dict[str, float], list[int], dict, dict] | None:
    """Baut und löst das MILP; None wenn nicht optimal / leere Matrix."""
    if not matrix:
        logger.error("MILP: Optimierungsmatrix ist leer.")
        return None

    inputs = _prepare_milp_inputs(
        matrix,
        verbose,
        consumers,
        consumer_remaining_kwh,
        spa_remaining_kwh,
        flex_indices,
        charging_contexts,
        filter_contexts,
        dt_h=dt_h,
    )
    model = _build_milp_model_with_objective(
        matrix,
        battery_params,
        current_soc,
        k_push,
        inputs,
        consumer_continue_on,
        hk_max_export_kw=hk_max_export_kw,
        inbound_export_limit_kw=inbound_export_limit_kw,
        export_caps_kw=export_caps_kw,
        current_soc_by_id=current_soc_by_id,
        inverter_params=inverter_params,
        pv_systems=pv_systems,
        soc_hold_index=soc_hold_index,
        soc_hold_percent=soc_hold_percent,
    )
    _add_flex_side_constraints(
        model, matrix, inputs, verbose, consumer_continue_on, thermal_flex_contexts
    )
    _add_soc_anchor_constraints(
        model,
        matrix,
        battery_params,
        current_soc,
        verbose,
        soc_hold_index=soc_hold_index,
        soc_hold_percent=soc_hold_percent,
        sunrise_soc_min_index=sunrise_soc_min_index,
        terminal_soc_percent=terminal_soc_percent,
    )
    if plan_vendor_mode_enabled():
        add_vendor_mode_export_constraints(
            model,
            matrix,
            inverter_params if inverter_params is not None else _default_inverter_params(),
            first_slot=0 if soc_hold_index is None else soc_hold_index + 1,
        )

    if import_caps is not None:
        add_import_cap_constraints(model, import_caps)

    update_cbc_milp_context_from_row(matrix[0])
    status = solve_with_strict_fallback(model.prob, msg=False, verbose=verbose)
    if status != "Optimal":
        record_cbc_event("milp_no_optimal", final_status=status)
        return None
    return (
        model,
        inputs.preset_by_slot,
        inputs.remaining,
        inputs.schedule_indices,
        inputs.contexts,
        inputs.filters,
    )
