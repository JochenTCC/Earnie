"""Store charge target from the planned energy (HeatControl P3, level 2).

Design: docs/dev/heat-control-sg-ready.md § 6 (level 2) and § 7. Where the plan runs the
heat pump in the present slot, the target is the store temperature at the end of that run:
the measured ``T_eq`` plus the planned heat of the run, minus the net draw (house, hot
water, collector) and the store's loss over the same slots. The target stays inside the
band of levels 0 and 1 until P5: at least the setpoint, at most setpoint + boost, capped by
the reported maximum. ``0`` means "no target" (the plan does not run the generator now).

The deviation check compares the plan with the operating mode the controller reports.
"""
from __future__ import annotations

import logging
from typing import Any

from optimizer.thermal_model import compute_heat_loss_kw

logger = logging.getLogger(__name__)

NO_TARGET_C = 0.0
_RUN_EPS_KW = 1e-3

# Operating modes (ehal.heat_fields.OPERATING_MODES) in which a planned run cannot happen.
_BLOCKING_MODES: dict[int, str] = {4: "locked", 6: "fault"}


def store_charge_target_c(plan: Any, run_electric_kw: list[float], dt_h: float) -> float:
    """End temperature of the run that starts now; ``NO_TARGET_C`` without a run.

    ``plan`` is a ``LiveStorePlan``; ``run_electric_kw`` the planned electric power of the
    heat pump per slot from slot 0 on, ending with the last slot of the run.
    """
    if dt_h <= 0:
        raise ValueError("dt_h must be > 0")
    if not run_electric_kw or float(run_electric_kw[0]) <= _RUN_EPS_KW:
        return NO_TARGET_C
    if plan.capacity_kwh_per_k <= 0 or plan.jaz <= 0:
        raise ValueError(
            "Ladeziel: Speicherplan ohne Kapazität oder Wirkungsgrad, Ziel nicht berechenbar."
        )
    temp = float(plan.start_temp_c)
    for slot, power_kw in enumerate(run_electric_kw):
        hour = int(slot * dt_h)
        ambient = _at(plan.ambient_c, hour, "Außentemperatur")
        draw = _at(plan.draw_kw_by_hour, hour, "Wärmeentnahme")
        loss = compute_heat_loss_kw(temp, ambient, plan.heat_loss_kw_per_k)
        heat = float(power_kw) * plan.jaz
        temp += (heat - draw - loss) * dt_h / plan.capacity_kwh_per_k
    lower = float(plan.band.setpoint_c)
    upper = float(plan.charge_max_c)
    return round(min(max(temp, lower), upper), 1)


def _at(values: list[float], hour: int, label: str) -> float:
    if hour >= len(values):
        raise ValueError(f"Ladeziel: {label} der Speicherprognose reicht nicht bis Stunde {hour}.")
    return float(values[hour])


def planned_run_kw(model: Any, cid: str) -> list[float]:
    """Planned electric power of ``cid`` from slot 0 to the end of the present run."""
    from optimizer.milp_consumer_vars import _consumer_power_at

    consumer = next(c for c in model.planned_consumers if str(c["id"]) == cid)
    run: list[float] = []
    for t in range(model.horizon):
        power = float(_consumer_power_at(model, consumer, t))
        if power <= _RUN_EPS_KW:
            break
        run.append(power)
    return run


def heat_storage_targets(model: Any) -> dict[str, float]:
    """Charge target per heat pump with a Live store plan (empty outside Live)."""
    plans = getattr(model, "live_store_plans", None) or {}
    planned = {str(c["id"]) for c in model.planned_consumers}
    out: dict[str, float] = {}
    for cid, plan in plans.items():
        if cid not in planned:
            continue
        target = store_charge_target_c(plan, planned_run_kw(model, cid), float(model.dt_h))
        out[cid] = target
        if target > 0:
            logger.info(
                "Ladeziel %s: %.1f °C (Start %.1f °C, Band bis %.1f °C)",
                cid,
                target,
                plan.start_temp_c,
                plan.charge_max_c,
            )
    return out


def operating_mode_deviation(planned_run: bool, operating_mode: float | None) -> str | None:
    """Deviation of the reported operating mode from the plan; None when none is known.

    Only a planned run in a mode that cannot run counts (locked, fault). The controller's
    own runs (space heating, hot water) while Earnie plans none are normal operation, and a
    hot-water run during a planned space-heating charge only moves heat between the two.
    """
    if operating_mode is None or not planned_run:
        return None
    return _BLOCKING_MODES.get(int(operating_mode))


def attach_targets_to_observability(
    observability: list[dict] | None,
    targets: dict[str, float],
    consumer_powers: dict[str, float],
) -> None:
    """Add ``heat_control`` (target, planned run, deviation) to the heat-storage items."""
    from ehal.heat_fields import KIND_OPERATING_MODE

    for item in observability or []:
        if not isinstance(item, dict) or item.get("kind") != "heat_storage":
            continue
        cid = str(item.get("consumer_id") or "")
        planned_run = float(consumer_powers.get(cid, 0.0) or 0.0) > _RUN_EPS_KW
        mode = (item.get("feedback") or {}).get(KIND_OPERATING_MODE)
        deviation = operating_mode_deviation(planned_run, mode)
        if deviation:
            logger.warning(
                "Wärmepumpe %s: Plan lässt sie laufen, die Regelung meldet Betriebsart %s (%s).",
                cid,
                int(mode),
                deviation,
            )
        item["heat_control"] = {
            "target_c": targets.get(cid),
            "planned_run": planned_run,
            "operating_mode": mode,
            "deviation": deviation,
        }
