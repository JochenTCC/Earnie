"""Planning clock for the Live cycle (EarlyStart P1).

A regular cycle may start ``lead`` seconds before its quarter-hour tick ``T``
and must plan for slot ``[T, T+15)``. Inside :func:`planning_anchor` every
planning-relevant "now" (slot start, current hour, today's date, forecast
start) reads :func:`planning_now`, which returns ``max(real now, T)``: frozen
at ``T`` until the tick, real time afterwards (a late cycle stays in slot T).

Outside an anchor — UI, backtesting, out-of-band runs, tests —
:func:`planning_now` is plain ``datetime.now(tz)``.

Measurements keep the real clock on purpose (PV integral, power-interval
sampler, cons_data samples, API rate-limit guards, write timestamps).

Spec: ``docs/spec/early-start-scheduling.md`` §4.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone, tzinfo
from typing import Iterator

# Aware UTC instant of the tick the running cycle plans for, or None.
_anchor: ContextVar[datetime | None] = ContextVar("earnie_planning_anchor", default=None)


def _to_utc(moment: datetime) -> datetime:
    """Naive values are system-local, like ``datetime.now()``."""
    return moment.astimezone(timezone.utc)


@contextmanager
def planning_anchor(tick: datetime | None) -> Iterator[None]:
    """Plan for ``tick`` within this block; ``None`` keeps the real clock."""
    token = _anchor.set(None if tick is None else _to_utc(tick))
    try:
        yield
    finally:
        _anchor.reset(token)


def anchored_tick() -> datetime | None:
    """The anchored tick as system-local naive datetime, or None."""
    anchor = _anchor.get()
    if anchor is None:
        return None
    return anchor.astimezone().replace(tzinfo=None)


def planning_now(tz: tzinfo | None = None) -> datetime:
    """``datetime.now(tz)``, but never before the anchored tick."""
    real = datetime.now(tz)
    anchor = _anchor.get()
    if anchor is None:
        return real
    if tz is None:
        anchor_local = anchor.astimezone().replace(tzinfo=None)
    else:
        anchor_local = anchor.astimezone(tz)
    return max(real, anchor_local)


# --- Refresh-ahead for in-process caches (EarlyStart prefetch) -------------

# Epoch seconds until which a cache entry must still be valid, or None.
_valid_until: ContextVar[float | None] = ContextVar("earnie_cache_valid_until", default=None)


@contextmanager
def cache_valid_until(moment: datetime | None) -> Iterator[None]:
    """Within this block, cache entries expiring before ``moment`` count as stale.

    The prefetch after a commit uses it so entries that would expire before the
    next cycle are refreshed now, in the idle time, instead of during the cycle.
    """
    token = _valid_until.set(None if moment is None else _to_utc(moment).timestamp())
    try:
        yield
    finally:
        _valid_until.reset(token)


def cache_entry_fresh(
    stored_at_epoch: float, ttl_sec: float, *, now_epoch: float | None = None
) -> bool:
    """True when an entry stored at ``stored_at_epoch`` is valid now — and, inside
    :func:`cache_valid_until`, still at that moment.

    ``now_epoch``: the clock the cache stamped its entries with (default ``time.time()``).
    """
    import time

    reference = time.time() if now_epoch is None else now_epoch
    until = _valid_until.get()
    if until is not None and until > reference:
        reference = until
    return reference - stored_at_epoch < ttl_sec
