from __future__ import annotations

import os
import random

import pulp
import pytest

from optimizer import cbc_solver
from optimizer.cbc_solver import (
    DEFAULT_CBC_GAP_REL,
    DEFAULT_CBC_STRICT_TIME_LIMIT_SEC,
    ENV_GAP_ABS,
    ENV_GAP_REL,
    ENV_STRICT_TIME_LIMIT,
    apply_cbc_solver_env,
    build_cbc_solver_cmd,
    cbc_solver_settings_from_env,
    cbc_solver_settings_resolved,
    clear_cbc_solver_env,
    resolve_cbc_gap_rel,
    resolve_cbc_strict_time_limit_sec,
    solve_with_strict_fallback,
)


@pytest.fixture(autouse=True)
def _clear_env():
    clear_cbc_solver_env()
    yield
    clear_cbc_solver_env()


def test_default_gap_rel_is_ten_percent():
    assert resolve_cbc_gap_rel() == DEFAULT_CBC_GAP_REL
    assert resolve_cbc_strict_time_limit_sec() == DEFAULT_CBC_STRICT_TIME_LIMIT_SEC
    assert cbc_solver_settings_resolved() == {
        "gapRel": 0.10,
        "strict_time_limit_sec": 5.0,
    }


def test_env_overrides_gap_and_strict_limit():
    os.environ[ENV_GAP_REL] = "0.01"
    os.environ[ENV_STRICT_TIME_LIMIT] = "3"
    assert resolve_cbc_gap_rel() == 0.01
    assert resolve_cbc_strict_time_limit_sec() == 3.0


def test_strict_mode_omits_gap_rel():
    apply_cbc_solver_env(strict=True)
    assert resolve_cbc_strict_time_limit_sec() == 0.0
    cmd = build_cbc_solver_cmd(msg=False, strict=True)
    assert "gapRel" not in cmd.optionsDict
    assert cbc_solver_settings_from_env() == {"strict": True}


def test_build_cbc_solver_cmd_strict_with_time_limit():
    cmd = build_cbc_solver_cmd(msg=False, strict=True, time_limit=5.0)
    assert cmd.timeLimit == 5.0
    assert "gapRel" not in cmd.optionsDict


def test_solve_with_strict_fallback_uses_gap_on_timeout():
    prob = pulp.LpProblem("t", pulp.LpMinimize)
    x = pulp.LpVariable("x", lowBound=0)
    prob += x
    prob += x >= 1
    os.environ[ENV_STRICT_TIME_LIMIT] = "0.01"
    status = solve_with_strict_fallback(prob, msg=False)
    assert status == "Optimal"
    assert x.value() == pytest.approx(1.0)


class _SolverWithoutSolution:
    def actualSolve(self, lp):
        lp.status = pulp.LpStatusNotSolved
        return lp.status


def test_gap_stage_runs_with_its_own_time_limit(monkeypatch):
    limits = []

    def fake_cmd(**kwargs):
        limits.append(kwargs.get("time_limit"))
        return _SolverWithoutSolution()

    monkeypatch.setattr(cbc_solver, "_build_solver_cmd", fake_cmd)
    prob = pulp.LpProblem("t", pulp.LpMinimize)
    prob += pulp.LpVariable("x", lowBound=0)
    assert solve_with_strict_fallback(prob, msg=False) == "Not Solved"
    assert limits == [DEFAULT_CBC_STRICT_TIME_LIMIT_SEC, 15.0]


def _infeasible_problem() -> pulp.LpProblem:
    prob = pulp.LpProblem("infeasible", pulp.LpMinimize)
    x = pulp.LpVariable("x", lowBound=0, upBound=1)
    prob += x
    prob += x >= 2
    return prob


@pytest.mark.parametrize("backend", ["highs", "cbc"])
def test_proven_infeasible_strict_stage_skips_the_gap_stage(monkeypatch, backend):
    stages = []
    real_cmd = cbc_solver._build_solver_cmd

    def counting_cmd(**kwargs):
        stages.append("strict" if kwargs.get("strict") else "gap")
        return real_cmd(**kwargs)

    monkeypatch.setattr(cbc_solver, "_build_solver_cmd", counting_cmd)
    token = cbc_solver.set_milp_solver_override(backend)
    cbc_solver.begin_solve_log()
    try:
        status = solve_with_strict_fallback(_infeasible_problem(), msg=False)
    finally:
        cbc_solver.reset_milp_solver_override(token)
    log = cbc_solver.take_solve_log()

    assert status == "Infeasible"
    assert stages == ["strict"]
    assert len(log) == 1
    assert log[0]["stage"] == "strict"
    assert log[0]["strict_status"] == "Infeasible"
    assert log[0]["final_status"] == "Infeasible"
    assert "gap_elapsed_sec" not in log[0]


def test_no_solution_within_both_limits_is_not_optimal(monkeypatch):
    """The real solver: ``milp`` takes anything but ``Optimal`` to its Automatik path."""
    rng = random.Random(1)
    items = range(400)
    choice = [pulp.LpVariable(f"x{i}", cat="Binary") for i in items]
    prob = pulp.LpProblem("hard", pulp.LpMaximize)
    prob += pulp.lpSum(rng.randint(100, 999) * choice[i] for i in items)
    for _ in range(30):
        weights = [rng.randint(100, 999) for _ in items]
        prob += pulp.lpSum(weights[i] * choice[i] for i in items) <= sum(weights) // 2
    os.environ[ENV_STRICT_TIME_LIMIT] = "0.001"
    monkeypatch.setattr(cbc_solver, "GAP_STAGE_TIME_LIMIT_SEC", 0.001)
    assert solve_with_strict_fallback(prob, msg=False) == "Not Solved"


def test_build_cbc_solver_cmd_solves_with_gap():
    prob = pulp.LpProblem("t", pulp.LpMinimize)
    x = pulp.LpVariable("x", lowBound=0)
    prob += x
    prob += x >= 1
    apply_cbc_solver_env(gap_rel=0.1)
    prob.solve(build_cbc_solver_cmd(msg=False, gap_rel=0.1))
    assert pulp.LpStatus[prob.status] == "Optimal"
    assert x.value() == pytest.approx(1.0)
