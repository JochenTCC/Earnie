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
from .milp_result import (
    _extract_milp_plan,
    _log_milp_decision,
    extract_horizon_schedule,
)

logger = logging.getLogger(__name__)

_AUTOMATIK_FALLBACK = (0, 0.0, 99.0, {}, {}, EMPTY_MILP_PLAN, {})


def _build_milp_model_with_objective(
    matrix: list[dict[str, Any]],
    battery_params: dict,
    current_soc: float,
    k_push: float,
    inputs: _MilpInputs,
    consumer_continue_on: dict[str, bool] | None,
) -> MilpHorizonModel:
    """Horizontmodell samt Zielfunktion (Energiekosten + Batterie-Verschleiß)."""
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
    )
    wear_cent_per_kwh = 0.0
    if battery_params["battery_capacity_kwh"] > 0.0:
        wear_cent_per_kwh = config.get_battery_wear_cent_per_kwh(
            battery_params["battery_capacity_kwh"]
        )
    _add_milp_objective(
        model,
        matrix,
        k_push,
        inputs.ev_milp_by_id,
        wear_cent_per_kwh=wear_cent_per_kwh,
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
    _add_consumer_delivery_constraints(
        model,
        matrix,
        inputs.remaining,
        inputs.schedule_indices,
        inputs.contexts,
        verbose,
        filter_contexts=inputs.filters,
    )
    add_generic_flex_rolling_constraints(
        model,
        matrix,
        inputs.schedule_indices,
        inputs.contexts,
        consumer_continue_on,
        filter_contexts=inputs.filters,
    )
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
    battery_params: dict,
    current_soc: float,
    verbose: bool,
    *,
    soc_hold_index: int | None,
    soc_hold_percent: float | None,
    sunrise_soc_min_index: int | None,
    terminal_soc_percent: float | None,
) -> None:
    """SOC-Anker in Vorrangfolge: Hold-Slot, PV-only bis Sonnenaufgang, End-SoC."""
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
    battery_params: dict,
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
    battery_params: dict | None = None,
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
) -> tuple[int, float, float, dict[str, float], dict[str, int], dict[str, float], dict[str, dict]]:
    """
    Berechnet den optimalen Betriebsmodus und die Ziel-Leistung für den Loxone Miniserver.
    Optimiert Batterie und alle konfigurierten flexible_consumers gemeinsam per MILP.
    Rückgabe: (mode, target_power, target_soc, {consumer_id: leistung_kw},
               {consumer_id: pv_follow 0|1}, milp_plan, urgent_observability)
    """
    battery_params = battery_params or config.get_battery_params()
    trivial = _try_trivial_milp_skip(
        matrix,
        battery_params,
        consumers,
        consumer_remaining_kwh,
        spa_remaining_kwh,
    )
    if trivial is not None:
        return _trivial_optimizer_result(current_soc)
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
    )
    if solved is None:
        return _AUTOMATIK_FALLBACK

    model, preset_by_slot, remaining, schedule_indices, contexts, filters = solved
    controls = _extract_optimizer_controls_from_model(
        model, matrix, preset_by_slot, current_soc, battery_params
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
    battery_params: dict | None = None,
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
) -> list[dict[str, Any]]:
    """
    Ein CBC-Solve über die Matrix; Rückgabe: Stundenplan-Slots für Open-Loop / commit-K.

    Bei leerer Matrix oder nicht-optimalem Solve: ein Fallback-Slot (Automatik).
    """
    battery_params = battery_params or config.get_battery_params()
    if (
        _try_trivial_milp_skip(
            matrix,
            battery_params,
            consumers,
            consumer_remaining_kwh,
            spa_remaining_kwh,
        )
        is not None
    ):
        return trivial_horizon_schedule(len(matrix))
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
    )
    if solved is None:
        return [dict(_FALLBACK_SCHEDULE_SLOT)]
    model, preset_by_slot, _, _, _, _ = solved
    return extract_horizon_schedule(model, battery_params, preset_by_slot)


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
