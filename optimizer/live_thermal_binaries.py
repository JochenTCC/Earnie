"""Live: on/off decisions of thermal consumers are binary only in the near horizon.

In Live the thermal consumers (pool / SwimSpa store, heat pump, heating rod) plan over the
whole horizon (``thermal_rc_live``, ``milp_model._thermal_schedule_indices``). With quarter-hour
on/off variables and a store between them, the strict solve of a real cycle (REG-76: 181 slots)
did not prove its optimum in ten minutes (LP bound 1.6 % below the best plan after 60 s), where
the first-day model took one second.

Only the first slot is executed; each cycle plans again. So the far horizon only has to hold
the energy and the store band: from ``LIVE_THERMAL_BINARY_HOURS`` on these on-variables are
continuous in ``[0, 1]`` (the average share of the slot the consumer runs), and so are the
PV-follow switches of the same consumers (``pv_follow <= on`` would otherwise allow PV-follow
only at a full share). Start variables of the pulse limit follow the on-variable
(``thermal_flex_base.add_max_pulses_per_day_constraints``). The SE book keeps all binaries.

The window is counted in slots (``LIVE_THERMAL_BINARY_HOURS / dt_h``) from the first slot of the
plan, not in wall-clock hours: a partial first slot shifts its end by less than one slot.
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

import pulp

if TYPE_CHECKING:
    from optimizer.milp_horizon import MilpHorizonModel

logger = logging.getLogger(__name__)

# Hours from the plan start in which a Live thermal consumer switches on/off (binary).
LIVE_THERMAL_BINARY_HOURS = 12.0


def live_thermal_binary_slots(dt_h: float) -> int:
    """Number of leading slots whose thermal on-variables stay binary (slot count, see above)."""
    if dt_h <= 0:
        raise ValueError(f"Slotdauer muss positiv sein (ist {dt_h:g} h).")
    return int(math.ceil(LIVE_THERMAL_BINARY_HOURS / float(dt_h) - 1e-9))


def relax_far_live_thermal_binaries(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    book_indices: list[int] | None,
) -> list[str]:
    """Make the on-variables of Live thermal consumers continuous after the binary window.

    Must run before the thermal constraints are built (their start variables copy the type).
    Returns the ids of the consumers whose far slots were relaxed.
    """
    from optimizer.live_cycle_scope import is_live_thermal_planning
    from optimizer.thermal_flex_base import is_thermal_flex_consumer
    from optimizer.thermal_flex_context import is_heating_rod_consumer
    from optimizer.thermal_rc_live import is_live_thermal_rc_store

    if book_indices is not None or not is_live_thermal_planning(matrix):
        return []
    first_relaxed = live_thermal_binary_slots(float(model.dt_h))
    relaxed: list[str] = []
    for consumer in model.planned_consumers:
        cid = str(consumer["id"])
        if cid not in model.consumer_on:
            continue
        if not (
            is_thermal_flex_consumer(consumer)
            or is_heating_rod_consumer(consumer)
            or is_live_thermal_rc_store(consumer, matrix, book_indices)
        ):
            continue
        on_vars = model.consumer_on[cid]
        far_vars = list(on_vars[first_relaxed:])
        if cid in model.consumer_pv_follow:
            far_vars += model.consumer_pv_follow[cid][first_relaxed:]
        for var in far_vars:
            var.cat = pulp.LpContinuous
            var.lowBound, var.upBound = 0, 1
        if len(on_vars) > first_relaxed:
            relaxed.append(cid)
    if relaxed:
        logger.debug(
            "Live: Ein/Aus von %s ab Slot %d als Laufzeitanteil geplant.",
            ", ".join(relaxed),
            first_relaxed,
        )
    return relaxed


def is_relaxed_on_var(var: Any) -> bool:
    """True for an on-variable made continuous here (read as a share of the slot)."""
    return getattr(var, "cat", pulp.LpInteger) == pulp.LpContinuous
