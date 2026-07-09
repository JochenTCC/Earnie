"""MILP-Optimierung für Batterie und flexible Verbraucher."""
from __future__ import annotations

import logging
from typing import Any

import config
from . import battery as bat
from .cbc_events import record_cbc_event, update_cbc_milp_context_from_row
from .cbc_solver import solve_with_strict_fallback
from .eauto_milp import split_eauto_preset
from .filter_context import resolve_filter_contexts
from .milp_consumers import (
    _add_consumer_delivery_constraints,
    _collect_urgent_rule_observability,
    _consumer_powers_now,
    _consumer_pv_follow_now_all,
    _log_urgent_rule_observability,
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
from .milp_result import _extract_milp_plan, _log_milp_decision

logger = logging.getLogger(__name__)

_AUTOMATIK_FALLBACK = (0, 0.0, 99.0, {}, {}, EMPTY_MILP_PLAN, {})


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


def milp_optimizer(
    matrix: list[dict[str, Any]],
    current_hour: int,
    current_soc: float,
    battery_params: dict | None = None,
    k_push: float | None = None,
    verbose: bool = True,
    consumers: list | None = None,
    consumer_remaining_kwh: dict[str, float] | None = None,
    spa_cfg: dict | None = None,
    spa_remaining_kwh: float | None = None,
    flex_indices: list[int] | None = None,
    charging_contexts: dict[str, dict] | None = None,
    filter_contexts: dict[str, dict] | None = None,
    terminal_soc_percent: float | None = None,
    sunrise_soc_min_index: int | None = None,
) -> tuple[int, float, float, dict[str, float], dict[str, int], dict[str, float], dict[str, dict]]:
    """
    Berechnet den optimalen Betriebsmodus und die Ziel-Leistung für den Loxone Miniserver.
    Optimiert Batterie und alle konfigurierten flexible_consumers gemeinsam per MILP.
    Rückgabe: (mode, target_power, target_soc, {consumer_id: leistung_kw},
               {consumer_id: pv_follow 0|1}, milp_plan, urgent_observability)
    """
    if not matrix:
        logger.error("MILP: Optimierungsmatrix ist leer.")
        return _AUTOMATIK_FALLBACK

    battery_params = battery_params or config.get_battery_params()
    fallback_k_push = k_push if k_push is not None else config.get_push_price_cent()
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
    has_eauto = any(c.get("id") == "eauto" for c in planned_consumers)
    eauto_milp_params = config.get_eauto_milp_params() if has_eauto else None
    preset_powers, milp_consumers = split_eauto_preset(
        planned_consumers,
        matrix[:horizon],
        remaining,
        schedule_indices,
        contexts,
        eauto_milp_params,
    )
    fixed_flex_kw_t0 = sum(preset_powers.values())

    model = _build_milp_model(
        matrix,
        horizon,
        battery_params,
        current_soc,
        milp_consumers,
        fixed_flex_kw_t0,
        remaining,
        eauto_milp_params,
    )
    wear_cent_per_kwh = config.get_battery_wear_cent_per_kwh(
        battery_params["battery_capacity_kwh"]
    )
    _add_milp_objective(
        model,
        matrix,
        fallback_k_push,
        eauto_milp_params,
        wear_cent_per_kwh=wear_cent_per_kwh,
    )
    logged_simulation = bool(
        matrix and matrix[0].get("consumption_mode") == "logged_day"
    )
    _add_consumer_delivery_constraints(
        model,
        matrix,
        remaining,
        schedule_indices,
        contexts,
        verbose,
        filter_contexts=filters,
        include_urgent_deadline_constraint=not logged_simulation,
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
        return _AUTOMATIK_FALLBACK

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
    "milp_optimizer",
    "_add_consumer_delivery_constraints",
    "_add_milp_objective",
    "_add_sunrise_soc_min_constraint",
    "_add_terminal_soc_constraint",
    "_build_milp_model",
    "_derive_control_from_milp",
]
