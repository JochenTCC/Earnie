"""Loxone-Zugangsdaten in config/.env eintragen (Setup-Seite oder Sidebar)."""
from __future__ import annotations

import streamlit as st

import config
from integrations.loxone_connectivity import loxone_env_configured, verify_loxone_setup
from runtime_store.dotenv_io import validate_loxone_credentials, write_loxone_dotenv
from runtime_store.dotenv_loader import load_app_dotenv
from runtime_store.persist_paths import resolve_dotenv_path
from version import __version__


def _save_loxone_credentials(ip: str, user: str, password: str) -> str | None:
    """Speichert .env und lädt Config neu. Liefert Fehlermeldung oder None."""
    validation_error = validate_loxone_credentials(ip, user, password)
    if validation_error:
        return validation_error
    try:
        path = write_loxone_dotenv(ip, user, password)
    except ValueError as exc:
        return str(exc)
    except OSError as exc:
        return f"Datei konnte nicht geschrieben werden: {exc}"

    load_app_dotenv(override=True)
    config.reinit_config(require_loxone_credentials=True)
    st.success(f"Zugangsdaten gespeichert in `{path}`.")
    return None


def render_loxone_credentials_form(*, form_key: str = "loxone_setup_form") -> None:
    """Formular für Miniserver-IP, Benutzer und Passwort."""
    st.caption(f"Zieldatei: `{resolve_dotenv_path()}`")
    with st.form(form_key):
        ip = st.text_input("Miniserver-IP", placeholder="192.168.178.1")
        user = st.text_input("Benutzername")
        password = st.text_input("Passwort", type="password")
        submitted = st.form_submit_button("Speichern", type="primary")

    if not submitted:
        return

    error = _save_loxone_credentials(ip, user, password)
    if error:
        st.error(error)
        return
    st.rerun()


def render_loxone_verify_results() -> None:
    """Führt verify_loxone_setup aus und zeigt Ergebnisse (Sidebar/Expander)."""
    if not loxone_env_configured():
        st.caption("Zuerst Miniserver-Zugang speichern.")
        return
    if not st.button("Loxone-Merker testen", key="loxone_verify_button"):
        return

    with st.spinner("Lese konfigurierte Merker vom Miniserver …"):
        try:
            ok, results = verify_loxone_setup()
        except (FileNotFoundError, ValueError, KeyError) as exc:
            st.error(f"Prüfung abgebrochen: {exc}")
            return

    for item in results:
        target = f" ({item.io_name})" if item.io_name else ""
        line = f"**{item.label}**{target}: {item.detail}"
        if item.passed:
            st.success(line)
        elif item.severity == "warning":
            st.warning(line)
        else:
            st.error(line)
    if ok:
        st.success("Alle Loxone-Prüfungen erfolgreich.")
    else:
        failed = sum(
            1 for item in results if not item.passed and item.severity != "warning"
        )
        st.error(f"{failed} von {len(results)} Prüfungen fehlgeschlagen.")


def render_loxone_setup_page() -> None:
    """Volle Setup-Seite (Prod-Ersteinrichtung ohne Greenfield-Planungsphase)."""
    st.title("Ersteinrichtung: Loxone-Zugang")
    st.caption(f"Version {__version__}")
    st.info(
        "Bitte Miniserver-Zugangsdaten eintragen. Der Optimizer-Worker startet "
        "automatisch, sobald die Datei gespeichert ist."
    )
    render_loxone_credentials_form()
