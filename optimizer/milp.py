"""MILP-Optimierung für Batterie und flexible Verbraucher."""
from __future__ import annotations

import logging
from typing import Any

import config
from . import battery as bat
from .cbc_events import record_cbc_event, update_cbc_milp_context_from_row
from .cbc_solver import solve_with_strict_fallback
from .eauto_milp import (
    build_ev_milp_params_by_id,
    split_eauto_preset,
)
from .filter_context import resolve_filter_contexts
from .thermal_flex_context import (
    add_thermal_flex_constraints,
    is_thermal_flex_consumer,
    resolve_thermal_flex_contexts,
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
_FALLBACK_SCHEDULE_SLOT = {
    "milp_plan": dict(EMPTY_MILP_PLAN),
    "consumer_powers": {},
    "consumer_pv_follow": {},
    "planned_soc_percent": None,
}


def _day_indices(matrix: list[dict[str, Any]], horizon: int) -> list[int]:
    """Stunden im Planungshorizont, die zum selben Kalendertag wie t=0 gehören."""
    ref_date = matrix[0].get("date")
    if ref_date is None:
        return list(range(horizon))
    return [t for t in range(horizon) if matrix[t].get("date") == ref_date]


def _active_consumers(consumers: list | None) -> list:
    if consumers is not None:
        return consumers
    return config.get_flexible_consumers(optimizer_only=True)


def _remaining_kwh_by_consumer(
    active: list,
    consumer_remaining_kwh: dict[str, float] | None,
    spa_remaining_kwh: float | None,
) -> dict[str, float]:
    remaining: dict[str, float] = {}
    for consumer in active:
        cid = consumer["id"]
        if consumer_remaining_kwh and cid in consumer_remaining_kwh:
            remaining[cid] = max(0.0, float(consumer_remaining_kwh[cid]))
        else:
            remaining[cid] = float(consumer["daily_target_kwh"])
    if spa_remaining_kwh is not None and "swimspa" in remaining:
        remaining["swimspa"] = max(0.0, float(spa_remaining_kwh))
    return remaining


def _resolve_thermal_flex_contexts(
    matrix: list[dict[str, Any]],
    consumers: list,
    thermal_flex_contexts: dict[str, dict] | None,
) -> dict[str, dict]:
    if thermal_flex_contexts is not None:
        return thermal_flex_contexts
    if not any(is_thermal_flex_consumer(consumer) for consumer in consumers):
        return {}
    settings = config.get_resolved_runtime_settings()
    profile = settings.get("_house_profile")
    if not profile:
        return {}
    climate = None
    if matrix and matrix[0].get("consumption_mode") == "profile_spec":
        from data.modeled_climate import ModeledClimateContext

        climate = ModeledClimateContext.from_scenario(settings)
    return resolve_thermal_flex_contexts(
        matrix,
        consumers,
        profile,
        climate=climate,
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
) -> tuple[MilpHorizonModel, dict[str, float], dict[str, float], list[int], dict, dict] | None:
    """Baut und löst das MILP; None wenn nicht optimal / leere Matrix."""
    if not matrix:
        logger.error("MILP: Optimierungsmatrix ist leer.")
        return None

    active = _active_consumers(consumers)
    remaining = _remaining_kwh_by_consumer(active, consumer_remaining_kwh, spa_remaining_kwh)
    horizon = len(matrix)
    day_indices = _day_indices(matrix, horizon)
    schedule_indices = flex_indices if flex_indices is not None else day_indices
    contexts = charging_contexts or {}
    filters = (
        filter_contexts
        if filter_contexts is not None
        else resolve_filter_contexts(matrix[:horizon], active)
    )
    planned_consumers = filter_feasible_consumers(
        active,
        remaining,
        matrix[:horizon],
        schedule_indices,
        verbose,
        contexts,
        filters,
    )
    ev_milp_by_id = build_ev_milp_params_by_id(planned_consumers)
    preset_powers, milp_consumers = split_eauto_preset(
        planned_consumers,
        matrix[:horizon],
        remaining,
        schedule_indices,
        contexts,
    )
    model = _build_milp_model(
        matrix,
        horizon,
        battery_params,
        current_soc,
        milp_consumers,
        sum(preset_powers.values()),
        remaining,
        ev_milp_by_id,
        consumer_continue_on=consumer_continue_on,
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
        ev_milp_by_id,
        wear_cent_per_kwh=wear_cent_per_kwh,
    )
    _add_consumer_delivery_constraints(
        model,
        matrix,
        remaining,
        schedule_indices,
        contexts,
        verbose,
        filter_contexts=filters,
    )
    add_generic_flex_rolling_constraints(
        model,
        matrix,
        schedule_indices,
        contexts,
        consumer_continue_on,
        filter_contexts=filters,
    )
    add_thermal_flex_constraints(
        model,
        matrix[:horizon],
        schedule_indices,
        _resolve_thermal_flex_contexts(matrix[:horizon], active, thermal_flex_contexts),
        consumer_continue_on=consumer_continue_on,
    )
    if sunrise_soc_min_index is not None:
        e_min = (battery_params["min_soc"] / 100.0) * battery_params["battery_capacity_kwh"]
        _add_sunrise_soc_min_constraint(model, sunrise_soc_min_index, e_min)
        if verbose:
            logger.info(
                "MILP SOC-Anker Sonnenaufgang: Slot %d = %.1f %%",
                sunrise_soc_min_index,
                battery_params["min_soc"],
            )
    elif e_terminal := _terminal_soc_energy_kwh(battery_params, terminal_soc_percent):
        _add_terminal_soc_constraint(model, e_terminal)
        if verbose:
            logger.info(
                "MILP End-SoC-Randbedingung: %.1f %% (aktuell %.1f %%)",
                terminal_soc_percent,
                current_soc,
            )

    update_cbc_milp_context_from_row(matrix[0])
    status = solve_with_strict_fallback(model.prob, msg=False, verbose=verbose)
    if status != "Optimal":
        record_cbc_event("milp_no_optimal", final_status=status)
        return None
    return model, preset_powers, remaining, schedule_indices, contexts, filters


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
) -> tuple[int, float, float, dict[str, float], dict[str, int], dict[str, float], dict[str, dict]]:
    """
    Berechnet den optimalen Betriebsmodus und die Ziel-Leistung für den Loxone Miniserver.
    Optimiert Batterie und alle konfigurierten flexible_consumers gemeinsam per MILP.
    Rückgabe: (mode, target_power, target_soc, {consumer_id: leistung_kw},
               {consumer_id: pv_follow 0|1}, milp_plan, urgent_observability)
    """
    battery_params = battery_params or config.get_battery_params()
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
    )
    if solved is None:
        return _AUTOMATIK_FALLBACK

    model, preset_powers, remaining, schedule_indices, contexts, filters = solved
    milp_plan = _extract_milp_plan(model)
    consumer_powers, total_flex_power = _consumer_powers_now(model)
    consumer_powers.update(preset_powers)
    total_flex_power += sum(preset_powers.values())
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
    urgent_observability = _collect_urgent_rule_observability(
        model,
        matrix,
        remaining,
        schedule_indices,
        contexts,
        filters,
    )
    _log_urgent_rule_observability(urgent_observability)
    if verbose:
        _log_milp_decision(
            current_hour,
            matrix,
            current_soc,
            milp_plan,
            model,
            remaining,
            consumer_powers,
            consumer_pv_follow,
            mode,
            target_power,
            target_soc,
        )
    return (
        mode,
        target_power,
        target_soc,
        consumer_powers,
        consumer_pv_follow,
        milp_plan,
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
) -> list[dict[str, Any]]:
    """
    Ein CBC-Solve über die Matrix; Rückgabe: Stundenplan-Slots für Open-Loop / commit-K.

    Bei leerer Matrix oder nicht-optimalem Solve: ein Fallback-Slot (Automatik).
    """
    battery_params = battery_params or config.get_battery_params()
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
    )
    if solved is None:
        return [dict(_FALLBACK_SCHEDULE_SLOT)]
    model, preset_powers, _, _, _, _ = solved
    return extract_horizon_schedule(model, battery_params, preset_powers)


# Re-Exports für Tests und interne Aufrufer (API-Stabilität).
_add_consumer_delivery_constraints = _add_consumer_delivery_constraints
_add_milp_objective = _add_milp_objective
_add_sunrise_soc_min_constraint = _add_sunrise_soc_min_constraint
_add_terminal_soc_constraint = _add_terminal_soc_constraint
_build_milp_model = _build_milp_model
_derive_control_from_milp = bat._derive_control_from_milp

__all__ = [
    "MilpHorizonModel",
    "EMPTY_MILP_PLAN",
    "add_min_on_time_constraints",
    "filter_feasible_consumers",
    "milp_horizon_schedule",
    "milp_optimizer",
    "_add_consumer_delivery_constraints",
    "_add_milp_objective",
    "_add_sunrise_soc_min_constraint",
    "_add_terminal_soc_constraint",
    "_build_milp_model",
    "_derive_control_from_milp",
]
