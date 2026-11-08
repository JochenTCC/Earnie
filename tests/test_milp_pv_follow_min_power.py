"""The plan must not follow a PV surplus below the wallbox's minimum power."""
from __future__ import annotations

import pulp

from optimizer import milp_consumer_vars as vars_mod

_EV = {"id": "ev"}


def _solve(monkeypatch, surplus_kw: float) -> tuple[float, float]:
    """Force the EV on and reward low power: the cheapest allowed power and its pv_follow."""
    monkeypatch.setattr(vars_mod, "power_limits_kw", lambda consumer: (4.1, 11.0))
    monkeypatch.setattr(vars_mod, "uses_pv_follow", lambda consumer: True)
    prob = pulp.LpProblem("pv_follow", pulp.LpMinimize)
    on = [pulp.LpVariable("on_0", cat=pulp.LpBinary)]
    power: dict[str, list] = {}
    follow: dict[str, list] = {}
    vars_mod._add_setpoint_power_variables(
        prob, _EV, 1, [{"expected_p_pv": surplus_kw, "expected_p_act": 0.0}],
        {"ev": on}, power, {}, follow,
    )
    prob += on[0] == 1
    prob += power["ev"][0]
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[prob.status] == "Optimal"
    return float(power["ev"][0].varValue), float(follow["ev"][0].varValue)


def test_small_surplus_cannot_be_followed(monkeypatch) -> None:
    power_kw, follow = _solve(monkeypatch, surplus_kw=0.22)
    assert follow == 0.0
    assert power_kw >= 4.1 - 1e-6


def test_surplus_above_minimum_can_still_be_followed(monkeypatch) -> None:
    power_kw, follow = _solve(monkeypatch, surplus_kw=5.0)
    assert power_kw >= 4.1 - 1e-6
    assert follow in (0.0, 1.0)
    monkeypatch.setattr(vars_mod, "power_limits_kw", lambda consumer: (4.1, 11.0))
    prob = pulp.LpProblem("pv_follow_forced", pulp.LpMinimize)
    on = [pulp.LpVariable("on_0", cat=pulp.LpBinary)]
    power: dict[str, list] = {}
    follow_vars: dict[str, list] = {}
    vars_mod._add_setpoint_power_variables(
        prob, _EV, 1, [{"expected_p_pv": 5.0, "expected_p_act": 0.0}],
        {"ev": on}, power, {}, follow_vars,
    )
    prob += follow_vars["ev"][0] == 1
    prob += 0
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[prob.status] == "Optimal"
    assert abs(float(power["ev"][0].varValue) - 5.0) < 1e-6
