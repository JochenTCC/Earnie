"""Shared Shadow record/replay intercept for hub and ext:* HTTP clients (R3)."""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from runtime_store.shadow.hooks import record_transport
from runtime_store.shadow.mode import is_shadow_mode

T = TypeVar("T")


def safe_record(
    key: str,
    *,
    ok: bool,
    payload: Any = None,
    status: int | None = None,
    error: str | None = None,
) -> None:
    """Record a transport primitive; never raises to the caller."""
    try:
        record_transport(key, ok=ok, payload=payload, status=status, error=error)
    except Exception:  # noqa: BLE001 — recorder must never break callers
        pass


def hub_get(*, replay: Callable[[], T], live: Callable[[], T]) -> T:
    """Family A: Shadow replays only; Prod runs *live* (which records)."""
    if is_shadow_mode():
        return replay()
    return live()


def ext_get(
    *,
    replay: Callable[[], T | None],
    live: Callable[[], T],
    allow_live_fallback: bool,
) -> T | None:
    """Family B/C: Shadow tries *replay*; optional unrecorded live fallback.

    When ``allow_live_fallback`` is False (e.g. PV), a Shadow miss returns
    ``None`` and never calls *live*. Prod always calls *live* (which records).

    Family B *live* callables must skip ``safe_record`` when
    ``is_shadow_mode()`` is true (Shadow fallback must stay unrecorded).
    """
    if is_shadow_mode():
        hit = replay()
        if hit is not None:
            return hit
        if allow_live_fallback:
            return live()
        return None
    return live()
