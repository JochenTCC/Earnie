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


def test_strict_time_limit_at_most_caps_the_limit_and_restores_it():
    assert resolve_cbc_strict_time_limit_sec() == DEFAULT_CBC_STRICT_TIME_LIMIT_SEC
    with cbc_solver.strict_time_limit_at_most(3.0):
        assert resolve_cbc_strict_time_limit_sec() == 3.0
    assert resolve_cbc_strict_time_limit_sec() == DEFAULT_CBC_STRICT_TIME_LIMIT_SEC


def test_strict_time_limit_at_most_keeps_a_shorter_limit():
    """The SE's own strict limit (context override) is shorter than the savings cap."""
    token = cbc_solver.set_cbc_strict_time_limit_override(2.0)
    try:
        with cbc_solver.strict_time_limit_at_most(3.0):
            assert resolve_cbc_strict_time_limit_sec() == 2.0
        assert resolve_cbc_strict_time_limit_sec() == 2.0
    finally:
        cbc_solver.reset_cbc_strict_time_limit_override(token)


def test_strict_time_limit_at_most_leaves_the_env_limit():
    os.environ[ENV_STRICT_TIME_LIMIT] = "10"
    with cbc_solver.strict_time_limit_at_most(3.0):
        assert resolve_cbc_strict_time_limit_sec() == 10.0


def test_savings_plan_solves_with_the_shorter_strict_limit(monkeypatch):
    """The savings forecast is only shown: its strict stage stops earlier than the sent plan."""
    from optimizer import sim_costs, simulation

    seen = []

    class _Captured(Exception):
        pass

    def fake_simulate_horizon(*_args, **_kwargs):
        seen.append(resolve_cbc_strict_time_limit_sec())
        raise _Captured

    monkeypatch.setattr(simulation, "simulate_horizon", fake_simulate_horizon)
    with pytest.raises(_Captured):
        sim_costs._run_savings_horizons(
            [], 50.0, 50.0, None, None, None, sunrise_soc_min_index=None, consumers=None
        )
    assert seen == [cbc_solver.SAVINGS_STRICT_TIME_LIMIT_SEC]
    assert resolve_cbc_strict_time_limit_sec() == DEFAULT_CBC_STRICT_TIME_LIMIT_SEC


def test_real_highs_solution_at_the_limit_is_kept_inside_the_gap():
    """HiGHS stopped at the limit with a solution: kept when its gap is within ``gapRel``."""
    rng = random.Random(1)
    items = range(400)
    choice = [pulp.LpVariable(f"x{i}", cat="Binary") for i in items]
    prob = pulp.LpProblem("hard", pulp.LpMaximize)
    prob += pulp.lpSum(rng.randint(100, 999) * choice[i] for i in items)
    for _ in range(30):
        weights = [rng.randint(100, 999) for _ in items]
        prob += pulp.lpSum(weights[i] * choice[i] for i in items) <= sum(weights) // 2
    os.environ[ENV_STRICT_TIME_LIMIT] = "0.5"
    os.environ[ENV_GAP_REL] = "0.5"
    cbc_solver.begin_solve_log()
    status = solve_with_strict_fallback(prob, msg=False)
    (record,) = cbc_solver.take_solve_log()

    assert status == "Optimal"
    assert record["strict_time_limit_hit"] is True
    assert record["stage"] == cbc_solver.STAGE_STRICT_INCUMBENT
    assert 0.0 < record["strict_incumbent_gap"] <= 0.5
    assert "gap_elapsed_sec" not in record


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


class _FakeHighsInfo:
    def __init__(self, primal: float, bound: float) -> None:
        self.objective_function_value = primal
        self.mip_dual_bound = bound


class _FakeHighsModel:
    def __init__(self, primal: float, bound: float) -> None:
        self._info = _FakeHighsInfo(primal, bound)

    def getInfo(self) -> _FakeHighsInfo:  # noqa: N802 - mirrors the highspy API
        return self._info


class _FakeProb:
    def __init__(self, primal: float, bound: float) -> None:
        self.solverModel = _FakeHighsModel(primal, bound)


@pytest.mark.parametrize(
    ("primal", "bound", "expected"),
    [
        (10.0, 10.0, 0.0),
        (0.0, 0.0, 0.0),
        (-0.0, 0.0, 0.0),
        (0.0, -1.0, None),
        (10.0, 9.0, 0.1),
        (-10.0, -11.0, 0.1),
        (float("inf"), 1.0, None),
        (1.0, float("nan"), None),
    ],
)
def test_incumbent_gap_edge_cases(primal, bound, expected):
    gap = cbc_solver.incumbent_gap(_FakeProb(primal, bound), "highs")
    if expected is None:
        assert gap is None
    else:
        assert gap == pytest.approx(expected)


def test_incumbent_gap_unknown_for_cbc():
    assert cbc_solver.incumbent_gap(_FakeProb(10.0, 9.0), "cbc") is None
