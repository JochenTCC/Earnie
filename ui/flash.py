"""One-shot notices that survive ``st.rerun()``.

``st.success(...)`` directly before ``st.rerun()`` is discarded with the run, so
the user never sees the confirmation. ``flash(...)`` queues the message in the
session instead; ``render_flash_notices()`` (called once per run by ``app.py``,
before the page) shows and clears it.
"""
from __future__ import annotations

import streamlit as st

_SESSION_KEY = "_flash_notices"
_KINDS = ("success", "info", "warning", "error")


def flash(kind: str, text: str) -> None:
    """Queue ``text`` to be shown (as ``st.<kind>``) on the next run."""
    if kind not in _KINDS:
        raise ValueError(f"Unknown flash kind {kind!r}; expected one of {_KINDS}")
    queue = st.session_state.setdefault(_SESSION_KEY, [])
    queue.append((kind, str(text)))


def render_flash_notices() -> None:
    """Show and clear the notices queued by ``flash``."""
    for kind, text in st.session_state.pop(_SESSION_KEY, []):
        getattr(st, kind)(text)
