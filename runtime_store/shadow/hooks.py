"""Thin recorder entry points for transport primitives (never raise to caller)."""
from __future__ import annotations

from typing import Any

from runtime_store.shadow import feed as shadow_feed


def record_transport(
    key: str,
    *,
    ok: bool,
    payload: Any = None,
    status: int | None = None,
    error: str | None = None,
) -> None:
    shadow_feed.record(
        key,
        ok=ok,
        payload=payload,
        status=status,
        error=error,
    )


def record_event(key: str, *, payload: Any = None) -> None:
    shadow_feed.record(key, ok=True, payload=payload, status=None, error=None)
