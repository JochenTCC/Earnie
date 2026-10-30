"""Record and serve push-inbox reads for the cycle recorder and offline replay.

A live cycle opens a capture after ``begin_cycle``. Every optimizer read from
the push inbox (``read_push_value`` / ``read_push_counter`` /
``read_push_ready_by_time``) between then and ``finish_cycle`` is stored with
its first result. Replay serves those results instead of the inbox and fails
loud on a read the live cycle did not make.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

KIND_VALUE = "value"
KIND_COUNTER = "counter"
KIND_READY_BY_TIME = "ready_by_time"
KINDS = (KIND_VALUE, KIND_COUNTER, KIND_READY_BY_TIME)

_capture: ContextVar[dict | None] = ContextVar("earnie_push_read_capture", default=None)
_serve: ContextVar[dict | None] = ContextVar("earnie_push_read_serve", default=None)
_capture_token = None


def open_push_read_capture() -> dict:
    """Start storing push reads until :func:`close_push_read_capture`."""
    global _capture_token
    close_push_read_capture()
    bucket: dict = {kind: {} for kind in KINDS}
    _capture_token = _capture.set(bucket)
    return bucket


def close_push_read_capture() -> dict | None:
    """Stop capture and return the bucket, or None when capture was not open."""
    global _capture_token
    if _capture_token is None:
        return None
    bucket = _capture.get()
    _capture.reset(_capture_token)
    _capture_token = None
    return bucket


def note_push_read(kind: str, ehal_id: str, result: Any) -> None:
    """Keep the first result per id: the cycle planned with that value."""
    bucket = _capture.get()
    if bucket is None:
        return
    bucket[kind].setdefault(ehal_id, result)


def served_push_read(kind: str, ehal_id: str) -> tuple[bool, Any]:
    """``(True, result)`` during replay, ``(False, None)`` live."""
    serve = _serve.get()
    if serve is None:
        return False, None
    recorded = serve.get(kind) or {}
    if ehal_id not in recorded:
        raise ValueError(
            f"replay: push read {kind} '{ehal_id}' was not recorded in this cycle; "
            "the replay path reads a signal the live cycle did not read"
        )
    return True, recorded[ehal_id]


@contextmanager
def replay_push_reads(recorded: dict[str, Any]) -> Iterator[None]:
    """Serve ``recorded`` (``start_state.push_reads``) instead of the inbox."""
    if not isinstance(recorded, dict):
        raise TypeError("start_state.push_reads must be a dict")
    token = _serve.set({kind: dict(recorded.get(kind) or {}) for kind in KINDS})
    try:
        yield
    finally:
        _serve.reset(token)
