"""Import cap in the MILP: ``p_grid_buy[t] <= limit[t] + slack[t]``, never a hard limit.

A hard limit could make the model infeasible, and Live would then fall back to Automatik and lose
the whole plan. Slack keeps it solvable and names the slots that cannot hold.

Two penalties, because the bill counts only the month's highest quarter hour: one on the height of
the overshoot per month, so one slot at +4 kW costs more than four at +1 kW, and one per slot, so
slots below that height do not overshoot for free.
"""
from __future__ import annotations

import pulp

from .import_power_limit import ImportCaps
from .milp_horizon_types import MilpHorizonModel

SLACK_PENALTY_CENT_PER_KWH = 200.0
OVERSHOOT_PENALTY_CENT_PER_KW = 500.0


def add_import_cap_constraints(model: MilpHorizonModel, caps: ImportCaps) -> None:
    """Limit, slack and penalties on a model whose objective is already set."""
    if len(caps.limits_kw) < model.horizon:
        raise ValueError(
            f"Bezugsgrenze: {len(caps.limits_kw)} Slots, das Modell hat {model.horizon}."
        )
    overshoot_by_month: dict[str, pulp.LpVariable] = {}
    slack: list[pulp.LpVariable | None] = [None] * model.horizon
    penalty = pulp.LpAffineExpression()
    for t in range(model.horizon):
        limit = caps.limits_kw[t]
        if limit is None:
            continue
        month = caps.months[t]
        slack_var = pulp.LpVariable(f"import_cap_slack_{t}", lowBound=0.0)
        slack[t] = slack_var
        model.prob += model.p_grid_buy[t] <= limit + slack_var, f"import_cap_{t}"
        if month not in overshoot_by_month:
            overshoot = pulp.LpVariable(f"import_cap_overshoot_{month.replace('-', '_')}", lowBound=0.0)
            overshoot_by_month[month] = overshoot
            penalty += OVERSHOOT_PENALTY_CENT_PER_KW * overshoot
        model.prob += slack_var <= overshoot_by_month[month], f"import_cap_overshoot_link_{t}"
        penalty += SLACK_PENALTY_CENT_PER_KWH * model.dt_h * slack_var
    model.prob.objective += penalty
    model.import_cap_slack = slack
