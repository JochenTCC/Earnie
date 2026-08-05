"""Smarthome-Zugangsdaten: Loxone (.env) oder EHAL-Hub (config.json)."""
from __future__ import annotations

import streamlit as st

import config
from integrations.loxone_connectivity import (
    LoxoneCheck,
    loxone_env_configured,
    verify_loxone_setup,
)
from runtime_store.dotenv_io import (
    read_loxone_credentials,
    validate_loxone_credentials,
    write_loxone_dotenv,
)
from runtime_store.dotenv_loader import load_app_dotenv
from runtime_store.ehal_setup import (
    BACKEND_HA,
    BACKEND_LOXONE,
    BACKEND_OPENEMS,
    backend_label,
)
from runtime_store.persist_paths import resolve_dotenv_path
from ui.ehal_connection import (
    render_backend_selector,
    render_ha_connection_form,
    render_openems_connection_form,
)
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
    dotenv_path = resolve_dotenv_path()
    env_ip, env_user, env_pass = read_loxone_credentials()
    st.caption(f"Zieldatei: `{dotenv_path}`")
    with st.form(form_key):
        ip = st.text_input(
            "Miniserver-IP",
            value=env_ip,
            placeholder="192.168.178.1",
        )
        user = st.text_input("Benutzername", value=env_user)
        password = st.text_input("Passwort", value=env_pass, type="password")
        submitted = st.form_submit_button("Speichern", type="primary")

    if not submitted:
        return

    error = _save_loxone_credentials(ip, user, password)
    if error:
        st.error(error)
        return
    st.rerun()


def run_loxone_setup_verify() -> tuple[bool, list[LoxoneCheck]]:
    """Liest alle konfigurierten Loxone-Merker (wie scripts.verify_loxone_setup)."""
    if not loxone_env_configured():
        raise ValueError("Loxone-Zugangsdaten fehlen.")
    return verify_loxone_setup()


def display_loxone_verify_results(ok: bool, results: list[LoxoneCheck]) -> None:
    """Zeigt Ergebnisse von run_loxone_setup_verify in Streamlit."""
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


def render_loxone_verify_results(*, button_key: str = "loxone_verify_button") -> None:
    """Button + Anzeige für run_loxone_setup_verify."""
    if not loxone_env_configured():
        st.caption(
            "Zuerst Miniserver-Zugang speichern (Abschnitt **Anbindung** oben "
            "oder Ersteinrichtung)."
        )
        return
    if not st.button("Smarthome-Merker testen", key=button_key):
        return

    with st.spinner("Lese konfigurierte Merker vom Miniserver …"):
        try:
            ok, results = run_loxone_setup_verify()
        except (FileNotFoundError, ValueError, KeyError) as exc:
            st.error(f"Prüfung abgebrochen: {exc}")
            return

    display_loxone_verify_results(ok, results)


def render_hub_credentials(*, key_prefix: str, backend: str) -> None:
    """Show the credential form for the selected backend."""
    if backend == BACKEND_LOXONE:
        render_loxone_credentials_form(form_key=f"{key_prefix}_loxone_form")
    elif backend == BACKEND_HA:
        render_ha_connection_form(form_key=f"{key_prefix}_ha_form")
    elif backend == BACKEND_OPENEMS:
        render_openems_connection_form(form_key=f"{key_prefix}_openems_form")


def render_ehal_setup_page() -> None:
    """Blocking first-run: pick backend, then enter matching credentials."""
    st.title("Ersteinrichtung: Smarthome-Anbindung")
    st.caption(f"Version {__version__}")
    st.info(
        "Bitte Backend wählen und Zugangsdaten eintragen. Der Optimizer-Worker "
        "startet automatisch, sobald die Verbindung gespeichert ist."
    )
    backend = render_backend_selector(key_prefix="ehal_setup")
    st.markdown(f"**Zugang: {backend_label(backend)}**")
    render_hub_credentials(key_prefix="ehal_setup", backend=backend)

