"""Ersteinrichtung: Loxone-Zugangsdaten in config/.env eintragen."""
from __future__ import annotations

import streamlit as st

import config
from runtime_store.dotenv_io import validate_loxone_credentials, write_loxone_dotenv
from runtime_store.dotenv_loader import load_app_dotenv
from runtime_store.persist_paths import resolve_dotenv_path
from version import __version__


def render_loxone_setup_page() -> None:
    """Zeigt Setup-Formular und speichert config/.env bei erfolgreicher Eingabe."""
    st.title("Ersteinrichtung: Loxone-Zugang")
    st.caption(f"Version {__version__}")
    st.info(
        "Bitte Miniserver-Zugangsdaten eintragen. Der Optimizer-Worker startet "
        "automatisch, sobald die Datei gespeichert ist."
    )
    st.caption(f"Zieldatei: `{resolve_dotenv_path()}`")

    with st.form("loxone_setup_form"):
        ip = st.text_input("Miniserver-IP", placeholder="192.168.178.1")
        user = st.text_input("Benutzername")
        password = st.text_input("Passwort", type="password")
        submitted = st.form_submit_button("Speichern", type="primary")

    if not submitted:
        return

    validation_error = validate_loxone_credentials(ip, user, password)
    if validation_error:
        st.error(validation_error)
        return

    try:
        path = write_loxone_dotenv(ip, user, password)
    except ValueError as exc:
        st.error(str(exc))
        return
    except OSError as exc:
        st.error(f"Datei konnte nicht geschrieben werden: {exc}")
        return

    load_app_dotenv(override=True)
    config.reinit_config(require_loxone_credentials=True)
    st.success(f"Zugangsdaten gespeichert in `{path}`. Die Anwendung wird geladen …")
    st.rerun()
