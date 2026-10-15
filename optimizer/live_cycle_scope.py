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


def cycle_memo(key: Hashable, compute: Callable[[], T]) -> T:
    store = _scope.get()
    if store is None:
        return compute()
    if key not in store:
        store[key] = compute()
    return store[key]
