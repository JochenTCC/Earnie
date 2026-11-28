"""Live MILP store level of ``thermal_rc`` consumers (pool / SwimSpa).

In Live there is no SE book, and the generic delivery constraint would only allow the slots
of the current calendar day (``milp_inputs._day_indices``). For a pool whose RC target covers
the whole horizon that forced the heat for the night before midnight. Here the pool instead
keeps its water temperature in the band over the whole horizon (``add_store_level``), so the
solver heats in the cheapest slots that hold the band, before or after midnight.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from optimizer.thermal_store_model import STORE_SLACK_REPORT_KWH, add_store_level

if TYPE_CHECKING:
    from optimizer.milp_horizon import MilpHorizonModel

logger = logging.getLogger(__name__)


def is_live_thermal_rc_store(
    consumer: dict, matrix: list, book_indices: list[int] | None
) -> bool:
    """True for a ``thermal`` (RC) consumer planned in Live without an SE book."""
    from optimizer.live_cycle_scope import is_live_thermal_planning

    return (
        book_indices is None
        and consumer.get("daily_target_source") == "thermal"
        and is_live_thermal_planning(matrix)
    )


def add_thermal_rc_live_stores(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    contexts: dict[str, dict],
    filters: dict[str, dict],
    book_indices: list[int] | None,
) -> None:
    """Store level over the whole horizon for every Live ``thermal_rc`` consumer of the plan."""
    from optimizer.filter_context import apply_slot_availability_constraints
    from optimizer.milp_consumer_delivery import (
        _delivery_energy_expr,
        consumer_delivery_eligible_indices,
    )
    from optimizer.thermal_targets import thermal_rc_live_store

    horizon_indices = list(range(model.horizon))
    window = matrix[: model.horizon]
    for consumer in model.planned_consumers:
        if not is_live_thermal_rc_store(consumer, window, book_indices):
            continue
        cid = str(consumer["id"])
        ctx = contexts.get(cid)
        consumer_indices, eligible = consumer_delivery_eligible_indices(
            window, model.horizon, consumer, horizon_indices, ctx, filters.get(cid)
        )
        eligible = apply_slot_availability_constraints(
            model.prob,
            model.consumer_on,
            consumer,
            consumer_indices,
            eligible,
            model.consumer_p,
            model.consumer_pv_follow,
        )
        store = thermal_rc_live_store(consumer, window, float(model.dt_h))
        eligible_set = set(eligible)

        def heat_at(slot: int, *, _consumer=consumer, _eligible=eligible_set, _store=store):
            if slot not in _eligible:
                return 0.0
            return _delivery_energy_expr(model, _consumer, [slot]) * _store.efficiency

        level = add_store_level(model, f"{cid}_rc", store, horizon_indices, heat_at)
        recovery = _add_recovery_floor(model, consumer, store, level, eligible_set)
        if model.thermal_rc_levels is None:
            model.thermal_rc_levels = {}
        model.thermal_rc_levels[cid] = (store, level, recovery)


def _add_recovery_floor(
    model: MilpHorizonModel, consumer: dict, store, level, eligible_set: set[int]
) -> list[Any]:
    """Water below the band at the start: back into the band as fast as the heater can.

    ``add_store_level`` lets a start below the band drift toward the band with the leak only,
    which for a pool (time constant of days) would let the plan stay below it for the whole
    horizon. Like ``plan_minimum_heating``, the floor here follows full heating on every
    eligible slot until the band minimum is reached, then holds it; slack at the band's price.
    Returns the slack variables (empty when the start is in or above the band).
    """
    import pulp

    from optimizer.consumer_power import power_limits_kw
    from optimizer.thermal_store_model import STORE_SLACK_PENALTY_CENT_PER_KWH

    if store.start_kwh >= 0.0:
        return []
    cid = str(consumer["id"])
    _, max_kw = power_limits_kw(consumer)
    full_heat_kwh = float(max_kw) * float(model.dt_h) * store.efficiency
    reachable = store.start_kwh
    slack: list[Any] = []
    for slot in sorted(level.levels):
        reachable = (1.0 - store.leak_per_slot) * reachable - store.drain_kwh[slot]
        if slot in eligible_set:
            reachable += full_heat_kwh
        floor = min(0.0, reachable)
        below = pulp.LpVariable(f"{cid}_rc_recover_below_{slot}", lowBound=0.0)
        model.prob += (
            level.levels[slot] >= floor - below,
            f"{cid}_rc_recover_{slot}",
        )
        model.prob.objective += STORE_SLACK_PENALTY_CENT_PER_KWH * below
        slack.append(below)
    return slack


def report_thermal_rc_slack(model: MilpHorizonModel) -> None:
    """Warn when the plan cannot keep a pool in its band (never silent)."""
    for cid, (_store, level, recovery) in (model.thermal_rc_levels or {}).items():
        slack = max(
            [level.slack_kwh()]
            + [float(getattr(var, "varValue", None) or 0.0) for var in recovery]
        )
        if slack > STORE_SLACK_REPORT_KWH:
            logger.warning(
                "Pool/SwimSpa %s: Plan hält die Wassertemperatur nicht im Band "
                "(bis %.2f kWh außerhalb).",
                cid,
                slack,
            )
