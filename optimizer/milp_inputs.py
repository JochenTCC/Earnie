"""Eingabe-Auflösung und trivialer Fast Path für die MILP-Fenster.

Ausgelagert aus `optimizer/milp.py` (Dateigrößen-Limit). Die Namen werden in
`optimizer/milp.py` re-exportiert, damit Aufrufer und Tests stabil bleiben.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import config
from .eauto_milp import (
    build_ev_milp_params_by_id,
    split_eauto_preset,
)
from .filter_context import resolve_filter_contexts
from .milp_consumers import filter_feasible_consumers
from .milp_horizon import EMPTY_MILP_PLAN
from .slot_duration import validate_dt_h
from .thermal_flex_context import (
    is_thermal_flex_consumer,
    resolve_thermal_flex_contexts,
)

logger = logging.getLogger(__name__)

ENV_MILP_TRIVIAL_FAST_PATH = "EARNIE_MILP_TRIVIAL_FAST_PATH"

_FALLBACK_SCHEDULE_SLOT = {
    "milp_plan": dict(EMPTY_MILP_PLAN),
    "consumer_powers": {},
    "consumer_pv_follow": {},
    "planned_soc_percent": None,
}


def milp_trivial_fast_path_enabled() -> bool:
    """Env gate: unset/1 = on; 0/false/off/no = always solve (A/B baseline)."""
    raw = os.environ.get(ENV_MILP_TRIVIAL_FAST_PATH)
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() not in ("0", "false", "off", "no")


def is_trivial_milp_window(
    battery_params: dict,
    remaining_kwh: dict[str, float] | None,
) -> bool:
    """True when no battery capacity and no remaining flex energy to schedule."""
    capacity = float(battery_params.get("battery_capacity_kwh", 0.0) or 0.0)
    if capacity > 0.0:
        return False
    rem = remaining_kwh or {}
    return all(float(v or 0.0) <= 0.0 for v in rem.values())


def trivial_horizon_schedule(n: int) -> list[dict[str, Any]]:
    """Automatik / empty-flex slots — no solver (2.3.c.1 trivial window)."""
    if n < 0:
        raise ValueError(f"trivial schedule length must be >= 0 (got {n})")
    return [dict(_FALLBACK_SCHEDULE_SLOT) for _ in range(n)]


def _try_trivial_milp_skip(
    matrix: list[dict[str, Any]],
    battery_params: dict,
    consumers: list | None,
    consumer_remaining_kwh: dict[str, float] | None,
    spa_remaining_kwh: float | None,
) -> dict[str, float] | None:
    """
    If trivial fast path applies, return resolved remaining; else None.
    Caller must not invoke the solver when this returns a dict.
    """
    if not matrix or not milp_trivial_fast_path_enabled():
        return None
    active = _active_consumers(consumers)
    remaining = _remaining_kwh_by_consumer(
        active, consumer_remaining_kwh, spa_remaining_kwh
    )
    if not is_trivial_milp_window(battery_params, remaining):
        return None
    logger.debug("MILP trivial fast path (no battery, no remaining flex)")
    return remaining


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


@dataclass
class _MilpInputs:
    """Aufgelöste Eingaben eines Solve-Fensters (Verbraucher, Indizes, Kontexte)."""

    active: list
    remaining: dict[str, float]
    horizon: int
    schedule_indices: list[int]
    contexts: dict
    filters: dict
    milp_consumers: list
    ev_milp_by_id: dict
    preset_by_slot: dict
    fixed_flex_by_t: dict
    dt_h: float


def _prepare_milp_inputs(
    matrix: list[dict[str, Any]],
    verbose: bool,
    consumers: list | None,
    consumer_remaining_kwh: dict[str, float] | None,
    spa_remaining_kwh: float | None,
    flex_indices: list[int] | None,
    charging_contexts: dict[str, dict] | None,
    filter_contexts: dict[str, dict] | None,
    *,
    dt_h: float,
) -> _MilpInputs:
    """Restmengen, Planungsindizes, Filter und die Aufteilung E-Auto-Preset/MILP."""
    dt_h = validate_dt_h(dt_h)
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
        dt_h=dt_h,
    )
    ev_milp_by_id = build_ev_milp_params_by_id(planned_consumers)
    preset_by_slot, milp_consumers = split_eauto_preset(
        planned_consumers,
        matrix[:horizon],
        remaining,
        schedule_indices,
        contexts,
        dt_h=dt_h,
    )
    return _MilpInputs(
        active=active,
        remaining=remaining,
        horizon=horizon,
        schedule_indices=schedule_indices,
        contexts=contexts,
        filters=filters,
        milp_consumers=milp_consumers,
        ev_milp_by_id=ev_milp_by_id,
        preset_by_slot=preset_by_slot,
        fixed_flex_by_t={
            slot: sum(powers.values()) for slot, powers in preset_by_slot.items()
        },
        dt_h=dt_h,
    )
