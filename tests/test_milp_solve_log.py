"""Solve log of ``solve_with_strict_fallback``: stage, elapsed, time limit hit, objective."""

from __future__ import annotations

import pulp
import pytest

from optimizer import cbc_events
from optimizer import cbc_solver as cs
from runtime_store.recorder_replay import recorded_time_limit_hit, solve_hit_time_limit


class _FakeSolver:
    """Stands in for HiGHS: returns a fixed status pair without solving."""

    def __init__(self, status: int, sol_status: int, x: float = 1.0) -> None:
        self.status = status
        self.sol_status = sol_status
        self.x = x

    def actualSolve(self, lp, **_kwargs):  # noqa: N802 — PuLP solver interface
        for var in lp.variables():
            var.varValue = self.x
        lp.assignStatus(self.status, self.sol_status)
        return self.status


def _problem() -> pulp.LpProblem:
    prob = pulp.LpProblem("t", pulp.LpMinimize)
    x = pulp.LpVariable("x", lowBound=0)
    prob += 2 * x
    prob += x >= 1
    return prob


@pytest.fixture
def solver_stages(monkeypatch):
    """Queue fake results: one per solver stage the strict fallback builds."""
    queue: list[_FakeSolver] = []
    stages: list[bool] = []

    def build(*, backend, msg=False, strict=False, gap_rel=None, time_limit=None):
        stages.append(strict)
        return queue.pop(0)

    monkeypatch.setattr(cs, "_build_solver_cmd", build)
    monkeypatch.setattr(cs, "resolve_milp_solver", lambda: "highs")
    cs.clear_cbc_solver_env()
    return queue, stages


OPTIMAL = (pulp.LpStatusOptimal, pulp.LpSolutionOptimal)
AT_LIMIT = (pulp.LpStatusOptimal, pulp.LpSolutionIntegerFeasible)
NO_SOLUTION = (pulp.LpStatusNotSolved, pulp.LpSolutionNoSolutionFound)


def test_optimal_strict_solve_is_logged(solver_stages):
    queue, stages = solver_stages
    queue.append(_FakeSolver(*OPTIMAL))
    cs.begin_solve_log()
    assert cs.solve_with_strict_fallback(_problem()) == "Optimal"

    (record,) = cs.take_solve_log()
    assert stages == [True]
    assert record["stage"] == "strict"
    assert record["strict_time_limit_hit"] is False
    assert record["final_status"] == "Optimal"
    assert record["objective"] == pytest.approx(2.0)
    assert record["strict_limit_sec"] == cs.DEFAULT_CBC_STRICT_TIME_LIMIT_SEC
    assert solve_hit_time_limit(record) is False


def test_strict_stop_at_time_limit_falls_back_to_the_gap_stage(solver_stages):
    """A strict plan cut off at the limit depends on CPU speed: the gap stage replaces it."""
    queue, stages = solver_stages
    queue.extend([_FakeSolver(*AT_LIMIT, x=3.0), _FakeSolver(*OPTIMAL, x=1.0)])
    cbc_events.begin_cbc_event_collection()
    cs.begin_solve_log()
    prob = _problem()
    assert cs.solve_with_strict_fallback(prob) == "Optimal"

    assert stages == [True, False]
    assert pulp.value(prob.objective) == pytest.approx(2.0)
    (record,) = cs.take_solve_log()
    assert record["strict_time_limit_hit"] is True
    assert record["strict_status"] == cs.STRICT_STATUS_TIME_LIMIT
    assert record["stage"] == "gap"
    assert solve_hit_time_limit(record) is False
    (event,) = cbc_events.take_cbc_events()
    assert event["event"] == "strict_fallback"
    assert event["time_limit_hit"] is True


def test_gap_stage_stopped_at_its_limit_is_visible(solver_stages):
    queue, _ = solver_stages
    queue.extend([_FakeSolver(*AT_LIMIT), _FakeSolver(*AT_LIMIT)])
    cs.begin_solve_log()
    assert cs.solve_with_strict_fallback(_problem()) == "Optimal"

    (record,) = cs.take_solve_log()
    assert record["gap_time_limit_hit"] is True
    assert solve_hit_time_limit(record) is True


def test_gap_stage_runs_without_strict_solution(solver_stages):
    queue, stages = solver_stages
    queue.extend([_FakeSolver(*NO_SOLUTION), _FakeSolver(*OPTIMAL)])
    cs.begin_solve_log()
    assert cs.solve_with_strict_fallback(_problem()) == "Optimal"

    (record,) = cs.take_solve_log()
    assert stages == [True, False]
    assert record["stage"] == "gap"
    assert record["strict_status"] == "Not Solved"
    assert record["gap_time_limit_hit"] is False
    assert record["gap_rel"] == cs.DEFAULT_CBC_GAP_REL
    assert record["objective"] == pytest.approx(2.0)


def test_without_collection_nothing_is_kept(solver_stages):
    queue, _ = solver_stages
    queue.append(_FakeSolver(*OPTIMAL))
    cs.take_solve_log()
    cs.solve_with_strict_fallback(_problem())
    assert cs.take_solve_log() == []


def test_recorded_time_limit_hit_reads_the_entry():
    assert recorded_time_limit_hit({"outputs": {}}) is None
    hit = {"stage": "strict", "strict_time_limit_hit": True}
    clean = {"stage": "strict", "strict_time_limit_hit": False}
    assert recorded_time_limit_hit({"outputs": {"solver": [clean]}}) is False
    assert recorded_time_limit_hit({"outputs": {"solver": [clean, hit]}}) is True


def test_real_highs_solve_is_logged_as_optimal():
    cs.clear_cbc_solver_env()
    cs.begin_solve_log()
    assert cs.solve_with_strict_fallback(_problem()) == "Optimal"
    (record,) = cs.take_solve_log()
    assert record["backend"] == "highs"
    assert record["strict_time_limit_hit"] is False
    assert record["objective"] == pytest.approx(2.0)
