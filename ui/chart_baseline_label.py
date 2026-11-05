"""Name of the baseline in the charts: "BL Ziel" unless a view compares with another one."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import ContextManager

DEFAULT_BASELINE_LABEL = "BL Ziel"

_LABEL: ContextVar[str] = ContextVar("chart_baseline_label", default=DEFAULT_BASELINE_LABEL)


def baseline_label() -> str:
    return _LABEL.get()


@contextmanager
def _label_scope(label: str):
    token = _LABEL.set(label)
    try:
        yield
    finally:
        _LABEL.reset(token)


def chart_baseline_label_context(label: str | None) -> ContextManager:
    """Scope for one chart; ``None`` keeps the default."""
    return nullcontext() if label is None else _label_scope(label)
