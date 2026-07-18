"""Debounced auto-persist helper for Streamlit editors."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

import streamlit as st


def payload_fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def auto_persist(
    *,
    state_key: str,
    payload: Any,
    save: Callable[[], None],
    ready: bool = True,
    success_caption: str = "Gespeichert",
) -> bool:
    """
    Persist ``payload`` when it differs from the last saved fingerprint.

    Returns True when a write was performed. Skips when ``ready`` is False
    (incomplete / invalid form).
    """
    if not ready:
        return False
    fingerprint = payload_fingerprint(payload)
    last_key = f"_auto_persist_fp::{state_key}"
    if st.session_state.get(last_key) == fingerprint:
        return False
    save()
    st.session_state[last_key] = fingerprint
    st.caption(success_caption)
    return True
