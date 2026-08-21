"""Streamlit banner when Loxone HTTP auth fails (401/403)."""
from __future__ import annotations

import streamlit as st

from runtime_store.dotenv_io import loxone_dotenv_conflict
from runtime_store.loxone_auth_error import load_loxone_auth_error


def render_loxone_auth_error_banner() -> None:
    """Show persisted Loxone auth failure from runtime/loxone_auth_error.json."""
    error = load_loxone_auth_error()
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
            f"Bitte Zugangsdaten unter **Smarthome-Backend → Anbindung** prüfen und speichern.{extra}"
        )
    if conflict:
        canonical = conflict["canonical_path"]
        for item in conflict["conflicts"]:
            st.warning(
                f"Abweichende Zugangsdaten in `{item['path']}` — aktiv ist `{canonical}`. "
                "Unter **Smarthome-Backend → Anbindung** können Sie die anderen Werte übernehmen."
            )
