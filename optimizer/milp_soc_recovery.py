"""Start SoC outside the battery's limits: the plan leads it back, it does not jump.

A measured SoC below ``min_soc`` or above ``max_soc`` used to leave the model one slot to
reach the limit: forced grid charging or export in slot 0, or no solution at all (Automatik,
plan lost) when the battery's power did not cover the gap.

Now the energy may stay where it starts and return when the prices suit. Until it is back
inside the limits it only moves towards them (below ``min_soc`` no discharge, above ``max_soc``
no charge), and once inside it stays inside.
"""
from __future__ import annotations

import pulp

from .milp_horizon_types import _GridBatteryVars

_ENERGY_TOLERANCE_KWH = 1e-9


def _add_one_sided_recovery(
    prob: pulp.LpProblem,
    slug: str,
    energy: list,
    locked_power: list,
    *,
    e_start: float,
    e_limit: float,
    below: bool,
) -> None:
    """Relax the limit to the start energy and lock the power that leads away from it.

    ``recovered[t]`` = 1 says the energy is back inside the limit at the end of slot ``t``;
    it never falls back to 0. ``locked_power`` (discharge below the limit, charge above it)
    needs ``recovered`` at the start of its slot.
    """
    side = "low" if below else "high"
    recovered = [
        pulp.LpVariable(f"soc_recovered_{side}_{slug}_{t}", cat=pulp.LpBinary)
        for t in range(len(energy))
    ]
    for t, e_var in enumerate(energy):
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
        e_min, e_max = float(energy[0].lowBound), float(energy[0].upBound)
        e_start = float(e_init_by_ess[ess_id])
        slug = ess_id.replace("-", "_")
        if e_start < e_min - _ENERGY_TOLERANCE_KWH:
            _add_one_sided_recovery(
                prob,
                slug,
                energy,
                grid_vars.p_discharge_by_ess[ess_id],
                e_start=e_start,
                e_limit=e_min,
                below=True,
            )
        elif e_start > e_max + _ENERGY_TOLERANCE_KWH:
            _add_one_sided_recovery(
                prob,
                slug,
                energy,
                grid_vars.p_charge_by_ess[ess_id],
                e_start=e_start,
                e_limit=e_max,
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
