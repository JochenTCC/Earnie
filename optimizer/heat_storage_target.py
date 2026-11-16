"""Store charge target from the planned energy (HeatControl P3, level 2).

Design: docs/dev/heat-control-sg-ready.md § 6 (level 2), § 7 and § 8.6. Where the plan runs
the heat pump in the present slot, the target is the store temperature at the end of that
run, read from the store level of the MILP (HeatControl P4): band minimum + level / C. The
target stays inside the charge band: at least the setpoint, at most
``LiveStorePlan.charge_max_c`` (setpoint + boost capped by the reported maximum; with the
COP curve of HeatControl P5 and the target mapped, the reported maximum). ``0`` means "no
target" (the plan does not run the generator now).

The deviation check compares the plan with the operating mode the controller reports.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

NO_TARGET_C = 0.0
_RUN_EPS_KW = 1e-3

# Operating modes (ehal.heat_fields.OPERATING_MODES) in which a planned run cannot happen.
_BLOCKING_MODES: dict[int, str] = {4: "locked", 6: "fault"}


def store_temp_c(plan: Any, level_kwh: float) -> float:
    """Store temperature of a level [kWh above the band minimum]."""
    if plan.capacity_kwh_per_k <= 0:
        raise ValueError("Ladeziel: Speicherplan ohne Kapazität, Ziel nicht berechenbar.")
    return float(plan.band.min_c) + float(level_kwh) / float(plan.capacity_kwh_per_k)


def store_charge_target_c(plan: Any, run_slots: int, level_after_run_kwh: float | None) -> float:
    """End temperature of the run that starts now; ``NO_TARGET_C`` without a run.

    ``plan`` is a ``LiveStorePlan``; ``run_slots`` the length of the present run (0 = none);
    ``level_after_run_kwh`` the planned store level after its last slot.
    """
    if run_slots <= 0:
        return NO_TARGET_C
    if level_after_run_kwh is None:
        raise ValueError("Ladeziel: kein Speicherstand am Ende des Laufs.")
    temp = store_temp_c(plan, level_after_run_kwh)
    lower = float(plan.band.setpoint_c)
    upper = float(plan.charge_max_c)
    return round(min(max(temp, lower), upper), 1)


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


def forced_charge_ids(model: Any, matrix: list, curtail_kw: float) -> list[str]:
    """Heat pumps whose present run is a forced charge (SG-Ready state 4, HeatControl P5).

    Design § 7: the generator runs now while the buy price of the slot is negative or the
    plan curtails PV surplus in it. Only with the COP curve: without it the energy above the
    setpoint is not priced, and state 4 would let the controller charge beyond the plan.
    """
    plans = getattr(model, "live_store_plans", None) or {}
    if not matrix or not plans:
        return []
    if float(matrix[0]["k_act"]) >= 0.0 and float(curtail_kw) <= _RUN_EPS_KW:
        return []
    planned = {str(c["id"]) for c in model.planned_consumers}
    return sorted(
        cid
        for cid, plan in plans.items()
        if cid in planned and plan.efficiency.by_temperature and planned_run_kw(model, cid)
    )


def heat_storage_targets(model: Any, forced: tuple[str, ...] | list[str] = ()) -> dict[str, float]:
    """Charge target per heat pump with a Live store plan (empty outside Live).

    A heat pump in ``forced`` (state 4) gets the upper end of its band as the target.
    """
    plans = getattr(model, "live_store_plans", None) or {}
    levels = getattr(model, "live_store_levels", None) or {}
    planned = {str(c["id"]) for c in model.planned_consumers}
    out: dict[str, float] = {}
    for cid, plan in plans.items():
        if cid not in planned:
            continue
        run = planned_run_kw(model, cid)
        level_after = None
        if run:
            if cid not in levels:
                raise ValueError(f"Ladeziel {cid}: Speicherstand fehlt im MILP.")
            level_vars = levels[cid][1]
            last_slot = len(run) - 1  # the run starts at slot 0
            if last_slot not in level_vars.levels:
                raise ValueError(f"Ladeziel {cid}: kein Speicherstand für Slot {last_slot}.")
            level_after = level_vars.level_kwh(last_slot)
        target = store_charge_target_c(plan, len(run), level_after)
        if run and cid in forced:
            target = round(float(plan.charge_max_c), 1)
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


def store_level_report(model: Any) -> dict[str, dict]:
    """Planned store temperature per slot and the slack of the band, per Live heat pump (P4).

    Slack means the plan could not keep the store in its band (too little power, pulse limit,
    window); it is logged as a warning, never silent.
    """
    from optimizer.thermal_store_model import STORE_SLACK_REPORT_KWH

    plans = getattr(model, "live_store_plans", None) or {}
    out: dict[str, dict] = {}
    for cid, (store, level_vars) in (getattr(model, "live_store_levels", None) or {}).items():
        plan = plans.get(cid)
        if plan is None:
            continue
        slots = sorted(level_vars.levels)
        slack = level_vars.slack_kwh()
        if slack > STORE_SLACK_REPORT_KWH:
            logger.warning(
                "Wärmepumpe %s: Plan hält den Speicher nicht im Band (bis %.2f kWh außerhalb).",
                cid,
                slack,
            )
        out[cid] = {
            "planned_temp_c": [
                round(store_temp_c(plan, level_vars.level_kwh(slot)), 2) for slot in slots
            ],
            "terminal_min_temp_c": (
                None
                if store.terminal_min_kwh is None
                else round(store_temp_c(plan, store.terminal_min_kwh), 2)
            ),
            "band_slack_kwh": round(slack, 3),
        }
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
    levels: dict[str, dict] | None = None,
) -> None:
    """Add ``heat_control`` (target, planned run, deviation, planned store level) to the
    heat-storage items."""
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
            "store_level": (levels or {}).get(cid),
        }
