"""MILP-Optimierung für Batterie und flexible Verbraucher."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import config
from . import battery as bat
from .cbc_events import record_cbc_event, update_cbc_milp_context_from_row
from .cbc_solver import solve_with_strict_fallback
from .slot_duration import DEFAULT_DT_H
from .thermal_flex_context import add_thermal_flex_constraints
from .milp_inputs import (
    ENV_MILP_TRIVIAL_FAST_PATH,
    _FALLBACK_SCHEDULE_SLOT,
    _MilpInputs,
    _prepare_milp_inputs,
    _resolve_thermal_flex_contexts,
    _try_trivial_milp_skip,
    is_trivial_milp_window,
    milp_trivial_fast_path_enabled,
    trivial_horizon_schedule,
)
from .milp_consumers import (
    _add_consumer_delivery_constraints,
    _collect_urgent_rule_observability,
    _consumer_powers_now,
    _consumer_pv_follow_now_all,
    _log_urgent_rule_observability,
    add_generic_flex_rolling_constraints,
    add_min_on_time_constraints,
    block_flex_outside_book,
    filter_feasible_consumers,
)
from .milp_horizon import (
    EMPTY_MILP_PLAN,
    MilpHorizonModel,
    _add_milp_objective,
    _add_pv_only_charge_through_sunrise,
    _add_soc_equality_constraint,
    _add_sunrise_soc_min_constraint,
    _add_terminal_soc_constraint,
    _build_milp_model,
    _terminal_soc_energy_kwh,
)
from .import_power_limit import ImportCaps
from .milp_ev_pool import add_ev_pool_constraints
from .milp_import_cap import add_import_cap_constraints
from house_config.import_cap import MODE_OBSERVE, MODE_OPTIMIZE

from .import_cap_report import (
    NOT_PLANNED_AUTOMATIK,
    NOT_PLANNED_SHADOW,
    NOT_PLANNED_TRIVIAL,
    not_planned_report,
    not_planned_slot_marks,
    observe_report,
    plan_slot_marks,
    report_from_model,
)
from .milp_vendor_mode import add_vendor_mode_export_constraints, plan_vendor_mode_enabled
from .milp_result import (
    _extract_milp_plan,
    _log_milp_decision,
    extract_horizon_schedule,
)
from .milp_defaults import (  # noqa: F401  (re-exported for recorder_replay / facades)
    _default_battery_params,
    _default_inverter_params,
    _default_pv_systems,
    _primary_battery_params,
)

logger = logging.getLogger(__name__)

_AUTOMATIK_FALLBACK = (0, 0.0, 99.0, {}, {}, EMPTY_MILP_PLAN, {})


def _add_virtual_reserve_refill(
    model: MilpHorizonModel, matrix: list[dict[str, Any]], primary: dict
) -> None:
    """Deadline-bound virtual-reserve refill charge constraint (no-op without refill)."""
    refill_kwh = float(
        primary.get("_virtual_reserve_refill_kwh")
        or primary.get("_virtual_reserve_asap_kwh")
        or 0.0
    )
    if refill_kwh <= 1e-9:
        return
    from datetime import datetime, timezone

    from .milp_horizon import _add_virtual_reserve_deadline_charge

    deadline_raw = primary.get("_virtual_reserve_refill_deadline_utc")
    deadline = None
    if deadline_raw:
        try:
            deadline = datetime.fromisoformat(str(deadline_raw).replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
        except ValueError:
            deadline = None
    _add_virtual_reserve_deadline_charge(
        model,
        matrix=matrix,
        refill_kwh=refill_kwh,
        max_charge_kw=float(
            primary.get("max_charge_power_kw", primary.get("max_power_kw") or 0.0)
            or 0.0
        ),
        efficiency=float(primary.get("efficiency") or 1.0),
        deadline=deadline,
    )


def _base_level_start(
    battery_params: dict | list[dict],
    current_soc: float,
    soc_hold_index: int | None,
    soc_hold_percent: float | None,
) -> tuple[int, float]:
    """First slot the SoC base level tracks and the energy before it.

    With a SoC hold the plan starts for real after the hold: the slots before it are not replayed
    and only lead there.
    """
    capacity = float(_primary_battery_params(battery_params).get("battery_capacity_kwh") or 0.0)
    if soc_hold_index is not None and soc_hold_percent is not None:
        return soc_hold_index + 1, float(soc_hold_percent) / 100.0 * capacity
    return 0, float(current_soc) / 100.0 * capacity


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
    wear_cent_per_kwh = 0.0
    primary = _primary_battery_params(battery_params)
    _add_virtual_reserve_refill(model, matrix, primary)
    if float(primary.get("battery_capacity_kwh") or 0.0) > 0.0:
        # Wear from primary ESS capacity (multi-ESS wear refinement later).
        wear_cent_per_kwh = config.get_battery_wear_cent_per_kwh(
            float(primary["battery_capacity_kwh"])
        )
    _add_milp_objective(
        model,
        matrix,
        k_push,
        inputs.ev_milp_by_id,
        wear_cent_per_kwh=wear_cent_per_kwh,
        base_level_start=_base_level_start(
            battery_params, current_soc, soc_hold_index, soc_hold_percent
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
    add_thermal_flex_constraints(
        model,
        window,
        inputs.schedule_indices,
        _resolve_thermal_flex_contexts(window, inputs.active, thermal_flex_contexts),
        consumer_continue_on=consumer_continue_on,
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
    """SOC-Anker in Vorrangfolge: Hold-Slot, PV-only bis Sonnenaufgang, End-SoC."""
    battery_params = _primary_battery_params(battery_params)
    if soc_hold_index is not None and soc_hold_percent is not None:
        e_hold = (float(soc_hold_percent) / 100.0) * battery_params[
            "battery_capacity_kwh"
        ]
        _add_soc_equality_constraint(model, soc_hold_index, e_hold)
        if verbose:
            logger.info(
                "MILP SOC-Hold: Slot %d = %.1f %%",
                soc_hold_index,
                float(soc_hold_percent),
            )
    elif sunrise_soc_min_index is not None:
        # Floor already via e_batt lowBound; do not force == SOC_min (residual dump).
        min_soc = float(battery_params["min_soc"])
        below_min = float(current_soc) < min_soc - 1e-9
        refill_kwh = float(
            battery_params.get("_virtual_reserve_refill_kwh")
            or battery_params.get("_virtual_reserve_asap_kwh")
            or 0.0
        )
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
        elif refill_kwh > 1e-9:
            # Virtual reserve refill may need grid-side p_charge before sunrise;
            # PV-only would make that hard constraint Infeasible → Automatik fallback.
            if verbose:
                logger.warning(
                    "MILP SOC-Anker Sonnenaufgang: Slot %d — virtual reserve refill "
                    "%.3f kWh pending; skip PV-only so grid can fill carve-out",
                    sunrise_soc_min_index,
                    refill_kwh,
                )
        else:
            _add_pv_only_charge_through_sunrise(model, matrix, sunrise_soc_min_index)
            if verbose:
                logger.info(
                    "MILP SOC-Anker Sonnenaufgang: Slot %d PV-only charge (no hard SOC_min eq)",
                    sunrise_soc_min_index,
                )
    elif e_terminal := _terminal_soc_energy_kwh(battery_params, terminal_soc_percent):
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


@dataclass
class _OptimizerControls:
    """Loxone-Stellgrößen plus die daraus abgeleiteten Verbraucher-Maps."""

    mode: int
    target_power: float
    target_soc: float
    consumer_powers: dict[str, float]
    consumer_pv_follow: dict[str, int]
    milp_plan: dict[str, float]


def _extract_optimizer_controls_from_model(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    preset_by_slot: dict,
    current_soc: float,
    battery_params: dict,
) -> _OptimizerControls:
    """Modus/Leistung/SoC für t=0 inkl. E-Auto-Preset-Leistung außerhalb des MILP."""
    milp_plan = _extract_milp_plan(model)
    consumer_powers, total_flex_power = _consumer_powers_now(model)
    preset_t0 = preset_by_slot.get(0, {})
    consumer_powers.update(preset_t0)
    total_flex_power += sum(preset_t0.values())
    consumer_pv_follow = _consumer_pv_follow_now_all(model)
    mode, target_power, target_soc = bat._derive_control_from_milp(
        model,
        matrix,
        milp_plan,
        consumer_powers,
        total_flex_power,
        current_soc,
        battery_params,
    )
    return _OptimizerControls(
        mode=mode,
        target_power=target_power,
        target_soc=target_soc,
        consumer_powers=consumer_powers,
        consumer_pv_follow=consumer_pv_follow,
        milp_plan=milp_plan,
    )


def _warn_import_cap_not_planned(import_caps: ImportCaps | None, reason: str, mode: str) -> None:
    """Automatik and the trivial window plan nothing, so an import cap is not held by a plan.

    Observe mode never holds the cap, so there is nothing to warn about.
    """
    if import_caps is None or mode == MODE_OBSERVE:
        return
    limit = next(value for value in import_caps.limits_kw if value is not None)
    logger.warning("MILP: Bezugsgrenze (%.2f kW) nicht eingeplant: %s.", limit, reason)


def _with_not_planned_report(
    result: tuple,
    import_caps: ImportCaps | None,
    matrix: list[dict[str, Any]],
    reason: str,
    mode: str,
) -> tuple:
    """Automatik or trivial result; with a cap its plan says the cap was not planned."""
    if import_caps is None:
        return result
    plan = dict(result[5])
    plan["import_cap_report"] = not_planned_report(import_caps, matrix, reason, mode=mode)
    return result[:5] + (plan,) + result[6:]


def shadow_import_cap_report(
    executed_model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    import_caps: ImportCaps,
    solve_args: dict[str, Any],
    fallback_k_push: float,
) -> dict[str, Any]:
    """Observe mode (max-power plan P6d, decision O2): solve the same inputs again under the cap.

    ``solve_args`` are the keyword arguments of ``_solve_milp_to_model`` that gave
    ``executed_model`` (without ``import_caps``). The second plan is never executed; it only gives
    the report. If it does not solve, the executed plan stands and the report says so.
    """
    shadow = _solve_milp_to_model(**{**solve_args, "verbose": False}, import_caps=import_caps)
    if shadow is None:
        logger.warning(
            "MILP: Beobachtungsmodus – Plan mit Bezugsgrenze nicht gelöst; Viertelstunde ohne Vergleich."
        )
        return not_planned_report(import_caps, matrix, NOT_PLANNED_SHADOW, mode=MODE_OBSERVE)
    shadow_model, _preset, shadow_remaining, _idx, _contexts, _filters = shadow
    return observe_report(
        shadow_model, executed_model, matrix, import_caps, shadow_remaining, fallback_k_push
    )


def _trivial_optimizer_result(current_soc: float) -> (
    tuple[int, float, float, dict[str, float], dict[str, int], dict[str, float], dict[str, dict]]
):
    """Automatik-Stellgrößen des trivialen Fensters (kein Solve, SoC bleibt stehen)."""
    return (
        0,
        0.0,
        round(float(current_soc), 1),
        {},
        {},
        dict(EMPTY_MILP_PLAN),
        {},
    )


def milp_optimizer(
    matrix: list[dict[str, Any]],
    current_hour: int,
    current_soc: float,
    battery_params: dict | list[dict] | None = None,
    k_push: float | None = None,
    verbose: bool = True,
    consumers: list | None = None,
    consumer_remaining_kwh: dict[str, float] | None = None,
    spa_remaining_kwh: float | None = None,
    flex_indices: list[int] | None = None,
    charging_contexts: dict[str, dict] | None = None,
    filter_contexts: dict[str, dict] | None = None,
    terminal_soc_percent: float | None = None,
    sunrise_soc_min_index: int | None = None,
    consumer_continue_on: dict[str, bool] | None = None,
    thermal_flex_contexts: dict[str, dict] | None = None,
    soc_hold_index: int | None = None,
    soc_hold_percent: float | None = None,
    hk_max_export_kw: float | None = None,
    inbound_export_limit_kw: float | None = None,
    export_caps_kw: list[float | None] | None = None,
    current_soc_by_id: dict[str, float] | None = None,
    inverter_params: dict | list[dict] | None = None,
    pv_systems: list[dict] | None = None,
    import_caps: ImportCaps | None = None,
    import_cap_observe: bool = False,
) -> tuple[int, float, float, dict[str, float], dict[str, int], dict[str, float], dict[str, dict]]:
    """
    Berechnet den optimalen Betriebsmodus und die Ziel-Leistung für den Loxone Miniserver.
    Optimiert Batterie und alle konfigurierten flexible_consumers gemeinsam per MILP.
    Rückgabe: (mode, target_power, target_soc, {consumer_id: leistung_kw},
               {consumer_id: pv_follow 0|1}, milp_plan, urgent_observability)

    ``import_cap_observe``: observe mode of the import cap (P6d). The executed plan ignores
    ``import_caps``; a second plan with them gives ``milp_plan["import_cap_report"]``.
    """
    cap_mode = MODE_OBSERVE if import_cap_observe else MODE_OPTIMIZE
    battery_params = (
        battery_params if battery_params is not None else _default_battery_params()
    )
    primary = _primary_battery_params(battery_params)
    trivial = _try_trivial_milp_skip(
        matrix,
        primary,
        consumers,
        consumer_remaining_kwh,
        spa_remaining_kwh,
    )
    if trivial is not None:
        _warn_import_cap_not_planned(import_caps, "trivial window, no solve", cap_mode)
        return _with_not_planned_report(
            _trivial_optimizer_result(current_soc),
            import_caps,
            matrix,
            NOT_PLANNED_TRIVIAL,
            cap_mode,
        )
    fallback_k_push = k_push if k_push is not None else config.get_push_price_cent()
    solve_args: dict[str, Any] = {
        "matrix": matrix,
        "current_soc": current_soc,
        "battery_params": battery_params,
        "k_push": fallback_k_push,
        "verbose": verbose,
        "consumers": consumers,
        "consumer_remaining_kwh": consumer_remaining_kwh,
        "spa_remaining_kwh": spa_remaining_kwh,
        "flex_indices": flex_indices,
        "charging_contexts": charging_contexts,
        "filter_contexts": filter_contexts,
        "terminal_soc_percent": terminal_soc_percent,
        "sunrise_soc_min_index": sunrise_soc_min_index,
        "consumer_continue_on": consumer_continue_on,
        "thermal_flex_contexts": thermal_flex_contexts,
        "soc_hold_index": soc_hold_index,
        "soc_hold_percent": soc_hold_percent,
        "hk_max_export_kw": hk_max_export_kw,
        "inbound_export_limit_kw": inbound_export_limit_kw,
        "export_caps_kw": export_caps_kw,
        "current_soc_by_id": current_soc_by_id,
        "inverter_params": inverter_params,
        "pv_systems": pv_systems,
    }
    solved = _solve_milp_to_model(
        **solve_args, import_caps=None if import_cap_observe else import_caps
    )
    if solved is None:
        _warn_import_cap_not_planned(import_caps, "no optimal solve, Automatik", cap_mode)
        return _with_not_planned_report(
            _AUTOMATIK_FALLBACK, import_caps, matrix, NOT_PLANNED_AUTOMATIK, cap_mode
        )

    model, preset_by_slot, remaining, schedule_indices, contexts, filters = solved
    controls = _extract_optimizer_controls_from_model(
        model, matrix, preset_by_slot, current_soc, primary
    )
    if import_caps is not None and import_cap_observe:
        controls.milp_plan["import_cap_report"] = shadow_import_cap_report(
            model, matrix, import_caps, solve_args, fallback_k_push
        )
    elif import_caps is not None:
        controls.milp_plan["import_cap_report"] = report_from_model(
            model, matrix, import_caps, remaining
        )
    urgent_observability = _collect_urgent_rule_observability(
        model, matrix, remaining, schedule_indices, contexts, filters
    )
    _log_urgent_rule_observability(urgent_observability)
    if verbose:
        _log_milp_decision(
            current_hour, matrix, current_soc, controls.milp_plan, model,
            remaining, controls.consumer_powers, controls.consumer_pv_follow,
            controls.mode, controls.target_power, controls.target_soc,
        )
    return _optimizer_result_tuple(controls, urgent_observability)


def _optimizer_result_tuple(controls, urgent_observability: dict[str, dict]) -> tuple:
    """Public ``milp_optimizer`` result from the extracted controls."""
    return (
        controls.mode,
        controls.target_power,
        controls.target_soc,
        controls.consumer_powers,
        controls.consumer_pv_follow,
        controls.milp_plan,
        urgent_observability,
    )


def milp_horizon_schedule(
    matrix: list[dict[str, Any]],
    current_soc: float,
    battery_params: dict | list[dict] | None = None,
    k_push: float | None = None,
    verbose: bool = False,
    consumers: list | None = None,
    consumer_remaining_kwh: dict[str, float] | None = None,
    spa_remaining_kwh: float | None = None,
    flex_indices: list[int] | None = None,
    charging_contexts: dict[str, dict] | None = None,
    filter_contexts: dict[str, dict] | None = None,
    terminal_soc_percent: float | None = None,
    sunrise_soc_min_index: int | None = None,
    consumer_continue_on: dict[str, bool] | None = None,
    thermal_flex_contexts: dict[str, dict] | None = None,
    soc_hold_index: int | None = None,
    soc_hold_percent: float | None = None,
    hk_max_export_kw: float | None = None,
    inbound_export_limit_kw: float | None = None,
    export_caps_kw: list[float | None] | None = None,
    current_soc_by_id: dict[str, float] | None = None,
    inverter_params: dict | list[dict] | None = None,
    pv_systems: list[dict] | None = None,
    import_caps: ImportCaps | None = None,
) -> list[dict[str, Any]]:
    """
    Ein CBC-Solve über die Matrix; Rückgabe: Stundenplan-Slots für Open-Loop / commit-K.

    Bei leerer Matrix oder nicht-optimalem Solve: ein Fallback-Slot (Automatik).
    """
    battery_params = (
        battery_params if battery_params is not None else _default_battery_params()
    )
    primary = _primary_battery_params(battery_params)
    if (
        _try_trivial_milp_skip(
            matrix,
            primary,
            consumers,
            consumer_remaining_kwh,
            spa_remaining_kwh,
        )
        is not None
    ):
        schedule = trivial_horizon_schedule(len(matrix))
        if import_caps is None:
            return schedule
        return _with_slot_marks(schedule, not_planned_slot_marks(import_caps, len(schedule)))
    fallback_k_push = k_push if k_push is not None else config.get_push_price_cent()
    solved = _solve_milp_to_model(
        matrix,
        current_soc,
        battery_params,
        fallback_k_push,
        verbose,
        consumers,
        consumer_remaining_kwh,
        spa_remaining_kwh,
        flex_indices,
        charging_contexts,
        filter_contexts,
        terminal_soc_percent,
        sunrise_soc_min_index,
        consumer_continue_on,
        thermal_flex_contexts,
        soc_hold_index=soc_hold_index,
        soc_hold_percent=soc_hold_percent,
        hk_max_export_kw=hk_max_export_kw,
        inbound_export_limit_kw=inbound_export_limit_kw,
        export_caps_kw=export_caps_kw,
        current_soc_by_id=current_soc_by_id,
        inverter_params=inverter_params,
        pv_systems=pv_systems,
        import_caps=import_caps,
    )
    if solved is None:
        fallback = [dict(_FALLBACK_SCHEDULE_SLOT)]
        if import_caps is None:
            return fallback
        return _with_slot_marks(fallback, not_planned_slot_marks(import_caps, 1))
    model, preset_by_slot, remaining, _, _, _ = solved
    schedule = extract_horizon_schedule(model, primary, preset_by_slot)
    if import_caps is None:
        return schedule
    return _with_slot_marks(schedule, plan_slot_marks(model, matrix, import_caps, remaining))


def _with_slot_marks(
    schedule: list[dict[str, Any]], marks: list[dict[str, Any] | None]
) -> list[dict[str, Any]]:
    """Schedule slots with the import cap's limit and cause (SE log, P6c); slots without a limit stay."""
    return [slot if mark is None else {**slot, **mark} for slot, mark in zip(schedule, marks)]


# Re-Exports für Tests und interne Aufrufer (API-Stabilität).
_add_consumer_delivery_constraints = _add_consumer_delivery_constraints
_add_milp_objective = _add_milp_objective
_add_sunrise_soc_min_constraint = _add_sunrise_soc_min_constraint
_add_pv_only_charge_through_sunrise = _add_pv_only_charge_through_sunrise
_add_terminal_soc_constraint = _add_terminal_soc_constraint
_build_milp_model = _build_milp_model
_derive_control_from_milp = bat._derive_control_from_milp

__all__ = [
    "MilpHorizonModel",
    "EMPTY_MILP_PLAN",
    "ENV_MILP_TRIVIAL_FAST_PATH",
    "add_min_on_time_constraints",
    "filter_feasible_consumers",
    "is_trivial_milp_window",
    "milp_horizon_schedule",
    "milp_optimizer",
    "milp_trivial_fast_path_enabled",
    "trivial_horizon_schedule",
    "_add_consumer_delivery_constraints",
    "_add_milp_objective",
    "_add_pv_only_charge_through_sunrise",
    "_add_sunrise_soc_min_constraint",
    "_add_terminal_soc_constraint",
    "_build_milp_model",
    "_derive_control_from_milp",
]
