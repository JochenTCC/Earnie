"""Streamlit banner when Loxone HTTP auth fails (401/403)."""
from __future__ import annotations

import streamlit as st

from runtime_store.dotenv_io import loxone_dotenv_conflict
from runtime_store.loxone_auth_error import load_loxone_auth_error


def render_loxone_auth_error_banner() -> None:
    """Show persisted Loxone auth failure from runtime/loxone_auth_error.json.

    Only with ``live_environment`` in the UI modes: without it the UI does not run
    the live operation, so a leftover auth-gate file from an earlier daemon run
    is stale noise.
    """
    from runtime_store.shadow.mode import is_shadow_mode
    from ui.mode_selector import get_enabled_ui_mode_keys

    # Shadow never contacts the Miniserver; ignore leftover auth-gate files.
    live_ui = "live_environment" in get_enabled_ui_mode_keys()
    error = load_loxone_auth_error() if live_ui and not is_shadow_mode() else None
    conflict = loxone_dotenv_conflict()
    if not error and not conflict:
        return
    if error:
        status = error.get("http_status")
        status_txt = f"HTTP {status}" if status else "HTTP 401/403"
        detail = error.get("message", "unbekannt")
        extra = ""
        if "temporarily blocked" in detail.lower():
            extra = (
                " Ihre PC-IP ist am Miniserver vorübergehend gesperrt — "
                "einige Minuten warten, bevor Sie erneut testen."
            )
        st.error(
            f"**Loxone-Zugang verweigert ({status_txt})** — {detail}. "
            "Der Optimierer pausiert Miniserver-Zugriffe. "
            f"Bitte Zugangsdaten unter **Smarthome-Backend → Zugangsdaten** prüfen und speichern.{extra}"
        )
    if conflict:
        canonical = conflict["canonical_path"]
        for item in conflict["conflicts"]:
            st.warning(
                f"Abweichende Zugangsdaten in `{item['path']}` — aktiv ist `{canonical}`. "
                "Unter **Smarthome-Backend → Zugangsdaten** können Sie die anderen Werte übernehmen."
            )
