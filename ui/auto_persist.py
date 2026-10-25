"""Debounced auto-persist helper for Streamlit editors."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

import streamlit as st



SHADOW_READONLY_CAPTION = "Shadow-Modus: Konfiguration schreibgeschützt — nicht gespeichert."


class PersistRejected(Exception):
    """Raised by a ``save`` callback that refused the write.

    The callback has already shown why (``st.error``); ``auto_persist`` then
    neither records the payload as saved nor flashes ``Gespeichert``, and
    returns False so callers do not ``st.rerun()`` the message away.
    """


def require_saved(result: Any) -> Any:
    """Return ``result`` of a store save helper, or raise ``PersistRejected`` on ``None``."""
    if result is None:
        raise PersistRejected()
    return result


def warn_not_saved(subject: str, blockers: list[str]) -> None:
    """Tell the user why an incomplete form is not auto-saved (``ready`` is False)."""
    st.warning(
        f"{subject} noch nicht gespeichert: "
        + (", ".join(blockers) if blockers else "Formular unvollständig")
        + ". Beim Verlassen des Tabs geht der Entwurf verloren."
    )


def payload_fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def auto_persist(
    *,
    state_key: str,
    payload: Any,
    save: Callable[[], Any],
    ready: bool = True,
    success_caption: str = "Gespeichert",
) -> bool:
    """
    Persist ``payload`` when it differs from the last saved fingerprint.

    Returns True when a write was performed. Skips when ``ready`` is False
    (incomplete / invalid form). A ``save`` callback that raises
    ``PersistRejected`` leaves the fingerprint untouched and returns False. When Shadow shares Prod config (read-only),
    skips writes without crashing.

    Success captions survive one ``st.rerun()`` via a session flash key so
    callers that rerun after write still show ``Gespeichert``.
    """
    flash_key = f"_auto_persist_flash::{state_key}"
    pending_flash = st.session_state.pop(flash_key, None)
    if pending_flash:
        st.caption(str(pending_flash))

    if not ready:
        return False
    fingerprint = payload_fingerprint(payload)
    last_key = f"_auto_persist_fp::{state_key}"
    if st.session_state.get(last_key) == fingerprint:
        return False
    from runtime_store.shadow.errors import ConfigReadOnlyError
    from runtime_store.shadow.mode import is_shadow_config_readonly

    if is_shadow_config_readonly():
        st.session_state[last_key] = fingerprint
        st.caption(SHADOW_READONLY_CAPTION)
        return False
    try:
        save()
    except ConfigReadOnlyError:
        st.session_state[last_key] = fingerprint
        st.caption(SHADOW_READONLY_CAPTION)
        return False
    except PersistRejected:
        return False
    st.session_state[last_key] = fingerprint
    # Flash for post-rerun; caption now for callers that do not rerun.
    st.session_state[flash_key] = success_caption
    st.caption(success_caption)
    return True
