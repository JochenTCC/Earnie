"""Prototype: the plan obeys the battery's own mode in PV surplus slots (off by default).

In Automatik and Entladesperre a real battery charges every PV surplus. Without this constraint
the plan may export the surplus and leave the battery empty, the book then fills it anyway, and
the next window sells the difference. So export or curtailment needs one of three reasons: the
battery ends the slot full, it charges at its limit, or the plan forces a discharge, which is the
only mode that keeps PV away from the battery.
"""
from __future__ import annotations

import os
from typing import Any

import pulp

from house_config.battery_control import (
    BATTERY_CONTROL_FULL,
    BATTERY_CONTROL_LIMITS_ONLY,
    control_from_battery_params,
)

from .battery import effective_p_act, power_threshold_kw
from .milp_horizon_types import MilpHorizonModel
from .milp_inverter import coerce_inverter_params_list, ess_ids_on_inverter, optional_positive_kw

VENDOR_MODE_ENV = "EARNIE_PLAN_VENDOR_MODE"
# Forced discharge needs more than the threshold in ``_milp_full_control_setpoint``; the margin
# covers the SoC rounding to 0.1 % on the way from the plan to the setpoint.
FORCED_DISCHARGE_MARGIN = 1.1


def plan_vendor_mode_enabled() -> bool:
    return bool(os.environ.get(VENDOR_MODE_ENV, "").strip())


def _charge_cap_kw(model: MilpHorizonModel, ess_id: str, inverters: list[dict]) -> float:
    """Highest AC charge power the plan allows for this battery."""
    cap = float(model.p_charge_by_ess[ess_id][0].upBound)
    for inverter in inverters:
        inverter_id = str(inverter.get("id") or "").strip()
        if ess_id in ess_ids_on_inverter(model.ess_ids, model.battery_params_by_id, inverter_id):
            limit = optional_positive_kw(inverter, "max_ac_charge_kw")
            if limit is not None:
                cap = min(cap, limit)
    return cap


def add_vendor_mode_export_constraints(
    model: MilpHorizonModel,
    matrix: list[dict[str, Any]],
    inverter_params: dict | list[dict] | None,
    *,
    first_slot: int,
) -> None:
    """Export or curtail in a surplus slot only with a full, saturated or force-discharged battery.

    ``first_slot`` skips the slots before the book: they are never replayed and only lead to the
    SoC hold at SA₁.
    """
    if len(model.ess_ids) != 1:
        raise ValueError(
            f"{VENDOR_MODE_ENV} kann bisher nur einen Speicher abbilden, gefunden: {model.ess_ids}."
        )
    ess_id = model.ess_ids[0]
    params = model.battery_params_by_id[ess_id]
    capacity = float(params.get("battery_capacity_kwh") or 0.0)
    control = control_from_battery_params(params)
    if capacity <= 0.0 or control not in (BATTERY_CONTROL_FULL, BATTERY_CONTROL_LIMITS_ONLY):
        return
    charge_cap = _charge_cap_kw(model, ess_id, coerce_inverter_params_list(inverter_params))
    e_batt = model.e_batt_by_ess[ess_id]
    e_min, e_max = float(e_batt[0].lowBound), float(e_batt[0].upBound)
    max_discharge = float(model.p_discharge_by_ess[ess_id][0].upBound)
    forced_min_kw = FORCED_DISCHARGE_MARGIN * power_threshold_kw(float(params["max_power_kw"]))
    can_force = control == BATTERY_CONTROL_FULL and max_discharge >= forced_min_kw
    for t in range(first_slot, model.horizon):
        pv_kw = float(model.p_pv_curtail[t].upBound)
        p_con = effective_p_act(matrix[t], params)
        if pv_kw <= p_con:
            continue
        full = pulp.LpVariable(f"vendor_full_{t}", cat=pulp.LpBinary)
        model.prob += e_batt[t] >= e_min + (e_max - e_min) * full, f"vendor_full_link_{t}"
        allowed = pv_kw * full
        if pv_kw - p_con > charge_cap:
            saturated = pulp.LpVariable(f"vendor_saturated_{t}", cat=pulp.LpBinary)
            model.prob += model.p_charge[t] >= charge_cap * saturated, f"vendor_saturated_link_{t}"
            allowed += pv_kw * saturated
        if can_force:
            forced = pulp.LpVariable(f"vendor_forced_{t}", cat=pulp.LpBinary)
            model.prob += model.p_discharge[t] >= forced_min_kw * forced, f"vendor_forced_link_{t}"
            allowed += (pv_kw + max_discharge) * forced
        model.prob += (
            model.p_grid_sell[t] + model.p_pv_curtail[t] <= allowed,
            f"vendor_export_needs_reason_{t}",
        )
