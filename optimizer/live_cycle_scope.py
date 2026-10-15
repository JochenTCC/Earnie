"""Per-cycle memo for Live planning inputs (ThermalHorizon P2).

``main`` runs each cycle inside ``live_cycle_scope()``. Within the scope,
``cycle_memo`` computes a value once and hands the same object to every
caller of that cycle (e.g. the Live heat-storage plan is needed by flex
contexts, horizon targets and both MILP runs). Outside a scope — tests,
backtesting, UI — ``cycle_memo`` simply computes.
"""
from __future__ import annotations

from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar

T = TypeVar("T")

_scope: ContextVar[dict | None] = ContextVar("earnie_live_cycle_scope", default=None)


@contextmanager
def live_cycle_scope() -> Iterator[None]:
    token = _scope.set({})
    try:
        yield
    finally:
        _scope.reset(token)


def in_live_cycle() -> bool:
    return _scope.get() is not None


def is_live_thermal_planning(matrix: list | None) -> bool:
    """Thermal Live semantics (horizon plans, store floor) for this matrix.

    Inside a Live cycle always — even when the telemetry snapshot was rejected
    and the first row stays ``forecast`` — except for SE ``profile_spec``
    matrices. Outside (offline replay) the ``live_snapshot`` row marker
    decides, as before.
    """
    from optimizer.absent_mode import matrix_is_live_snapshot

    if not matrix:
        return False
    if matrix_is_live_snapshot(matrix):
        return True
    return in_live_cycle() and matrix[0].get("consumption_mode") != "profile_spec"


def cycle_memo(key: Hashable, compute: Callable[[], T]) -> T:
    store = _scope.get()
    if store is None:
        return compute()
    if key not in store:
        store[key] = compute()
    return store[key]
