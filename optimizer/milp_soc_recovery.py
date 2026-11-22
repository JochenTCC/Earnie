"""Start SoC outside the battery's limits: the plan leads it back, it does not jump.

A measured SoC below ``min_soc`` or above ``max_soc`` used to leave the model one slot to
reach the limit: forced grid charging or export in slot 0, or no solution at all (Automatik,
plan lost) when the battery's power did not cover the gap.

Now the energy may stay where it starts and return when the prices suit. Until it is back
inside the limits it only moves towards them (below ``min_soc`` no discharge, above ``max_soc``
no charge), and once inside it stays inside.

The virtual reserve of a powerstation raises the lower bound only in the slots where it pays
(Reserve P2, ``reserve_price_floor``); those bounds are per slot. A start between the configured
``min_soc`` and the reserve floor needs no recovery: the floor is only due in paying slots and
is capped to what the battery can reach. A start below ``min_soc`` is led back to each slot's
own bound, and ``recovered`` is forced in the first slot whose bound lies above ``min_soc`` (a
reserve floor): otherwise the solver could charge without setting it and skip the floor. That
bound is reachable from the start, because ``reachable_floor_kwh`` lowers an unreachable floor
to what the battery can reach, and never above ``min_soc`` while ``min_soc`` itself is out of
reach.
"""
from __future__ import annotations

import pulp

from .milp_horizon_types import _GridBatteryVars
from .reserve_price_floor import BASE_MIN_SOC_KEY as VIRTUAL_RESERVE_BASE_MIN_SOC_KEY

_ENERGY_TOLERANCE_KWH = 1e-9


def _add_one_sided_recovery(
    prob: pulp.LpProblem,
    slug: str,
    energy: list,
    locked_power: list,
    *,
    e_start: float,
    e_limits: list[float],
    below: bool,
    due_slot: int | None = None,
) -> None:
    """Relax the limit to the start energy and lock the power that leads away from it.

    ``recovered[t]`` = 1 says the energy is back inside the limit at the end of slot ``t``;
    it never falls back to 0. ``locked_power`` (discharge below the limit, charge above it)
    needs ``recovered`` at the start of its slot. ``due_slot``: the energy must be back by the
    end of this slot (``recovered`` = 1 there).
    """
    side = "low" if below else "high"
    recovered = [
        pulp.LpVariable(f"soc_recovered_{side}_{slug}_{t}", cat=pulp.LpBinary)
        for t in range(len(energy))
    ]
    for t, e_var in enumerate(energy):
        e_limit = e_limits[t]
        if below:
            e_var.lowBound = e_start
            prob += (
                e_var >= e_start + (e_limit - e_start) * recovered[t],
                f"soc_recovery_{side}_{slug}_{t}",
            )
        else:
            e_var.upBound = e_start
            prob += (
                e_var <= e_start - (e_start - e_limit) * recovered[t],
                f"soc_recovery_{side}_{slug}_{t}",
            )
        max_power = float(locked_power[t].upBound)
        if t == 0:
            prob += locked_power[t] <= 0.0, f"soc_recovery_lock_{side}_{slug}_{t}"
            continue
        prob += recovered[t] >= recovered[t - 1], f"soc_recovery_keep_{side}_{slug}_{t}"
        prob += (
            locked_power[t] <= max_power * recovered[t - 1],
            f"soc_recovery_lock_{side}_{slug}_{t}",
        )
    if due_slot is not None:
        prob += recovered[due_slot] == 1, f"soc_recovery_due_{side}_{slug}"


def add_soc_recovery_constraints(
    prob: pulp.LpProblem,
    grid_vars: _GridBatteryVars,
    e_init_by_ess: dict[str, float],
) -> dict[str, tuple[float, float]]:
    """Recovery constraints for every battery that starts outside its limits.

    Returns per such battery the SoC range in % its plan can take: the configured limits,
    widened to the start SoC. Empty when every battery starts inside its limits; the model
    then has no extra variables.
    """
    widened: dict[str, tuple[float, float]] = {}
    for ess_id in grid_vars.ess_ids:
        params = grid_vars.battery_params_by_id[ess_id]
        capacity = float(params.get("battery_capacity_kwh") or 0.0)
        if capacity <= 0.0:
            continue
        energy = grid_vars.e_batt_by_ess[ess_id]
        if not energy:
            continue
        lows = [float(e.lowBound) for e in energy]
        highs = [float(e.upBound) for e in energy]
        e_max = max(highs)
        # Per-slot lower bounds (virtual reserve floor): recovery is about the configured
        # min_soc only; the floor is capped to what the battery can reach from the start.
        base_min_soc = params.get(VIRTUAL_RESERVE_BASE_MIN_SOC_KEY)
        e_min = (
            float(base_min_soc) / 100.0 * capacity if base_min_soc is not None else min(lows)
        )
        e_start = float(e_init_by_ess[ess_id])
        slug = ess_id.replace("-", "_")
        if e_start < e_min - _ENERGY_TOLERANCE_KWH:
            # Reserve floor (per-slot bound above min_soc): due in its first slot.
            due_slot = next(
                (t for t, low in enumerate(lows) if low > e_min + _ENERGY_TOLERANCE_KWH),
                None,
            )
            _add_one_sided_recovery(
                prob,
                slug,
                energy,
                grid_vars.p_discharge_by_ess[ess_id],
                e_start=e_start,
                e_limits=lows,
                below=True,
                due_slot=due_slot,
            )
        elif e_start > e_max + _ENERGY_TOLERANCE_KWH:
            _add_one_sided_recovery(
                prob,
                slug,
                energy,
                grid_vars.p_charge_by_ess[ess_id],
                e_start=e_start,
                e_limits=highs,
                below=False,
            )
        else:
            continue
        start_percent = e_start / capacity * 100.0
        widened[ess_id] = (
            min(e_min / capacity * 100.0, start_percent),
            max(e_max / capacity * 100.0, start_percent),
        )
    return widened
