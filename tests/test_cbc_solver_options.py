from __future__ import annotations

import os

import pulp
import pytest

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
        "strict_time_limit_sec": 3.0,
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


def test_build_cbc_solver_cmd_solves_with_gap():
    prob = pulp.LpProblem("t", pulp.LpMinimize)
    x = pulp.LpVariable("x", lowBound=0)
    prob += x
    prob += x >= 1
    apply_cbc_solver_env(gap_rel=0.1)
    prob.solve(build_cbc_solver_cmd(msg=False, gap_rel=0.1))
    assert pulp.LpStatus[prob.status] == "Optimal"
    assert x.value() == pytest.approx(1.0)
