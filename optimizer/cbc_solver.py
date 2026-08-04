"""MILP solver options (CBC default; optional HiGHS). Two-stage: strict → gapRel."""
from __future__ import annotations

import logging
import os
import time
from contextvars import ContextVar, Token
from typing import Any, Literal

import pulp

from optimizer.cbc_events import maybe_record_strict_timing
from runtime_store.env_vars import is_truthy, read_env

logger = logging.getLogger(__name__)

DEFAULT_CBC_GAP_REL = 0.10
DEFAULT_CBC_STRICT_TIME_LIMIT_SEC = 3.0
DEFAULT_MILP_SOLVER: Literal["cbc", "highs"] = "highs"
VALID_MILP_SOLVERS = frozenset({"cbc", "highs"})

_CBC_ENV_SUFFIXES = (
    "CBC_GAP_REL",
    "CBC_GAP_ABS",
    "CBC_STRICT",
    "CBC_STRICT_TIME_LIMIT_SEC",
    "CBC_PRIMAL_TOLERANCE",
    "CBC_INTEGER_TOLERANCE",
)

ENV_GAP_REL = "EARNIE_CBC_GAP_REL"
ENV_GAP_ABS = "EARNIE_CBC_GAP_ABS"
ENV_STRICT_TIME_LIMIT = "EARNIE_CBC_STRICT_TIME_LIMIT_SEC"
ENV_MILP_SOLVER = "EARNIE_MILP_SOLVER"
HIGHS_THREADS = 1

_cbc_gap_rel_override: ContextVar[float | None] = ContextVar(
    "cbc_gap_rel_override",
    default=None,
)
_cbc_strict_time_limit_override: ContextVar[float | None] = ContextVar(
    "cbc_strict_time_limit_override",
    default=None,
)
_milp_solver_override: ContextVar[str | None] = ContextVar(
    "milp_solver_override",
    default=None,
)


def _read_optional_float_env(suffix: str) -> float | None:
    raw = read_env(suffix)
    if not raw:
        return None
    return float(raw)


def _is_strict_cbc_mode() -> bool:
    return is_truthy("CBC_STRICT")


def resolve_cbc_gap_rel() -> float:
    """Relativer MIP-Gap für Stufe 2 (und Default ohne Strict-Versuch)."""
    if _is_strict_cbc_mode():
        return DEFAULT_CBC_GAP_REL
    env_gap = _read_optional_float_env("CBC_GAP_REL")
    if env_gap is not None:
        return env_gap
    ctx_gap = _cbc_gap_rel_override.get()
    if ctx_gap is not None:
        return ctx_gap
    return DEFAULT_CBC_GAP_REL


def resolve_cbc_strict_time_limit_sec() -> float:
    """Zeitlimit für Strict-Stufe; 0 = Strict-Versuch überspringen."""
    if _is_strict_cbc_mode():
        return 0.0
    env_limit = _read_optional_float_env("CBC_STRICT_TIME_LIMIT_SEC")
    if env_limit is not None:
        return max(0.0, float(env_limit))
    ctx_limit = _cbc_strict_time_limit_override.get()
    if ctx_limit is not None:
        return max(0.0, float(ctx_limit))
    return DEFAULT_CBC_STRICT_TIME_LIMIT_SEC


def set_cbc_gap_rel_override(gap_rel: float | None) -> Token:
    return _cbc_gap_rel_override.set(gap_rel)


def reset_cbc_gap_rel_override(token: Token) -> None:
    _cbc_gap_rel_override.reset(token)


def set_cbc_strict_time_limit_override(seconds: float | None) -> Token:
    return _cbc_strict_time_limit_override.set(seconds)


def reset_cbc_strict_time_limit_override(token: Token) -> None:
    _cbc_strict_time_limit_override.reset(token)


def _normalize_milp_solver(raw: str) -> Literal["cbc", "highs"]:
    name = raw.strip().lower()
    if name not in VALID_MILP_SOLVERS:
        raise ValueError(
            f"Unknown MILP solver {raw!r}; expected one of {sorted(VALID_MILP_SOLVERS)}."
        )
    return name  # type: ignore[return-value]


def resolve_milp_solver() -> Literal["cbc", "highs"]:
    """Env EARNIE_MILP_SOLVER first, then SE ContextVar, else HiGHS default."""
    env_raw = read_env("MILP_SOLVER")
    if env_raw:
        return _normalize_milp_solver(env_raw)
    ctx = _milp_solver_override.get()
    if ctx:
        return _normalize_milp_solver(ctx)
    return DEFAULT_MILP_SOLVER


def set_milp_solver_override(solver: str | None) -> Token:
    return _milp_solver_override.set(solver)


def reset_milp_solver_override(token: Token) -> None:
    _milp_solver_override.reset(token)


def _require_highs_available() -> None:
    solver = pulp.HiGHS(msg=False)
    if not solver.available():
        raise RuntimeError(
            "MILP solver 'highs' selected but HiGHS is not available. "
            "Install with: pip install highspy  (or pip install -e \".[highs]\")"
        )


def build_highs_solver_cmd(
    *,
    msg: bool = False,
    strict: bool = False,
    gap_rel: float | None = None,
    time_limit: float | None = None,
) -> pulp.LpSolver:
    """Build PuLP HiGHS (highspy) solver; threads=1 for fair SE multi-worker runs."""
    _require_highs_available()
    kwargs: dict[str, Any] = {"msg": msg, "threads": HIGHS_THREADS}
    if time_limit is not None and time_limit > 0:
        kwargs["timeLimit"] = time_limit
    gap_abs = _read_optional_float_env("CBC_GAP_ABS")
    if gap_abs is not None:
        kwargs["gapAbs"] = gap_abs
    if not strict:
        kwargs["gapRel"] = resolve_cbc_gap_rel() if gap_rel is None else gap_rel
    return pulp.HiGHS(**kwargs)


def _append_env_options(settings: dict[str, Any]) -> None:
    gap_abs = _read_optional_float_env("CBC_GAP_ABS")
    if gap_abs is not None:
        settings["gapAbs"] = gap_abs
    options: list[str] = []
    primal = _read_optional_float_env("CBC_PRIMAL_TOLERANCE")
    if primal is not None:
        options.append(f"primalTolerance={primal}")
    integer = _read_optional_float_env("CBC_INTEGER_TOLERANCE")
    if integer is not None:
        options.append(f"integerTolerance={integer}")
    if options:
        settings["options"] = options


def build_cbc_solver_cmd(
    *,
    msg: bool = False,
    strict: bool = False,
    gap_rel: float | None = None,
    time_limit: float | None = None,
) -> pulp.PULP_CBC_CMD:
    settings: dict[str, Any] = {"msg": msg}
    if time_limit is not None and time_limit > 0:
        settings["timeLimit"] = time_limit
    if strict:
        _append_env_options(settings)
        return pulp.PULP_CBC_CMD(**settings)

    settings["gapRel"] = resolve_cbc_gap_rel() if gap_rel is None else gap_rel
    _append_env_options(settings)
    return pulp.PULP_CBC_CMD(**settings)


def cbc_solver_settings_resolved() -> dict[str, Any]:
    """Effektive Einstellungen für Stufe 2 inkl. Strict-Zeitlimit."""
    settings: dict[str, Any] = {
        "gapRel": resolve_cbc_gap_rel(),
        "strict_time_limit_sec": resolve_cbc_strict_time_limit_sec(),
    }
    gap_abs = _read_optional_float_env("CBC_GAP_ABS")
    if gap_abs is not None:
        settings["gapAbs"] = gap_abs
    if _is_strict_cbc_mode():
        settings["strict"] = True
    return settings


def cbc_solver_settings_from_env() -> dict[str, Any]:
    """Nur explizite Env-Overrides (für Diagnose/Benchmarks)."""
    if _is_strict_cbc_mode():
        return {"strict": True}
    settings: dict[str, Any] = {}
    gap_rel = _read_optional_float_env("CBC_GAP_REL")
    if gap_rel is not None:
        settings["gapRel"] = gap_rel
    limit = _read_optional_float_env("CBC_STRICT_TIME_LIMIT_SEC")
    if limit is not None:
        settings["strict_time_limit_sec"] = limit
    gap_abs = _read_optional_float_env("CBC_GAP_ABS")
    if gap_abs is not None:
        settings["gapAbs"] = gap_abs
    return settings


def _build_solver_cmd(
    *,
    backend: Literal["cbc", "highs"],
    msg: bool = False,
    strict: bool = False,
    gap_rel: float | None = None,
    time_limit: float | None = None,
) -> pulp.LpSolver:
    if backend == "highs":
        return build_highs_solver_cmd(
            msg=msg,
            strict=strict,
            gap_rel=gap_rel,
            time_limit=time_limit,
        )
    return build_cbc_solver_cmd(
        msg=msg,
        strict=strict,
        gap_rel=gap_rel,
        time_limit=time_limit,
    )


def solve_with_strict_fallback(
    prob: pulp.LpProblem,
    *,
    msg: bool = False,
    verbose: bool = False,
) -> str:
    """
    Zweistufig: kurzer Strict-Lauf, bei fehlender Optimalität Fallback auf gapRel.
    EARNIE_CBC_STRICT=1: nur Strict ohne Limit (Benchmarks).
    Backend: resolve_milp_solver() → highs (default) or cbc.
    """
    backend = resolve_milp_solver()
    label = "HiGHS" if backend == "highs" else "CBC"

    if _is_strict_cbc_mode():
        prob.solve(_build_solver_cmd(backend=backend, msg=msg, strict=True))
        return pulp.LpStatus[prob.status]

    strict_limit = resolve_cbc_strict_time_limit_sec()
    gap_rel = resolve_cbc_gap_rel()

    if strict_limit > 0:
        t0 = time.perf_counter()
        prob.solve(
            _build_solver_cmd(
                backend=backend,
                msg=msg,
                strict=True,
                time_limit=strict_limit,
            )
        )
        elapsed = time.perf_counter() - t0
        status = pulp.LpStatus[prob.status]
        if status == "Optimal":
            maybe_record_strict_timing(
                strict_limit_sec=strict_limit,
                strict_elapsed_sec=elapsed,
                strict_status=status,
                gap_rel=gap_rel,
            )
            return status
        maybe_record_strict_timing(
            strict_limit_sec=strict_limit,
            strict_elapsed_sec=elapsed,
            strict_status=status,
            gap_rel=gap_rel,
        )
        if verbose:
            print(
                f"{label} strict ({strict_limit:.1f} s) Status {status} "
                f"→ Fallback gapRel={gap_rel * 100:.1f}%"
            )

    prob.solve(_build_solver_cmd(backend=backend, msg=msg, gap_rel=gap_rel))
    final_status = pulp.LpStatus[prob.status]
    return final_status


def clear_cbc_solver_env() -> None:
    for suffix in _CBC_ENV_SUFFIXES:
        os.environ.pop(f"EARNIE_{suffix}", None)
    os.environ.pop("EARNIE_MILP_SOLVER", None)


def apply_cbc_solver_env(
    *,
    gap_rel: float | None = None,
    gap_abs: float | None = None,
    strict: bool = False,
    strict_time_limit_sec: float | None = None,
    primal_tolerance: float | None = None,
    integer_tolerance: float | None = None,
) -> None:
    clear_cbc_solver_env()
    if strict:
        os.environ["EARNIE_CBC_STRICT"] = "1"
    if gap_rel is not None:
        os.environ["EARNIE_CBC_GAP_REL"] = str(gap_rel)
    if gap_abs is not None:
        os.environ["EARNIE_CBC_GAP_ABS"] = str(gap_abs)
    if strict_time_limit_sec is not None:
        os.environ["EARNIE_CBC_STRICT_TIME_LIMIT_SEC"] = str(strict_time_limit_sec)
    if primal_tolerance is not None:
        os.environ["EARNIE_CBC_PRIMAL_TOLERANCE"] = str(primal_tolerance)
    if integer_tolerance is not None:
        os.environ["EARNIE_CBC_INTEGER_TOLERANCE"] = str(integer_tolerance)
