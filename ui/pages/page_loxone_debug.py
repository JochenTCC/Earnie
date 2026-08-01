"""EHAL-Com: Debug-Seite für Anbindung, Live-Lesen und Live-Schreiben."""
from __future__ import annotations

import streamlit as st

import config
from runtime_store.ehal_setup import BACKEND_HA, BACKEND_LOXONE, BACKEND_OPENEMS
from ui.ehal_connection import (
    render_backend_selector,
    render_ha_connection_form,
    render_openems_connection_form,
)
from ui.help_hint import render_page_title_with_help
from ui.loxone_debug import render_loxone_debug_block
from ui.setup_dotenv import render_loxone_credentials_form
from ui.setup_readiness import (
    is_betrieb_unlocked,
    is_planning_ready,
    needs_planning_onboarding,
)

_EHAL_COM_HELP = (
    "Anbindung und Live-Übersicht für Loxone, Home Assistant (EHAL) oder OpenEMS. "
    "Live-Lesen zeigt `sens_*`/`get_*` mit EHAL-Feld und Backend-Mapping; "
    "Live-Schreiben die Schreibvorgänge (`set_*`, Flex-Freigabe/`set_enable`) "
    "aus dem Produktiv-Lauf von main.py. "
    "Loxone-Bindings werden entity-zentriert unter "
    "Loxone Struktur → EHAL Mapping gepflegt. "
    "Außerplanmäßige Optimierung: Earnie_Request_Optimize (Port 8541)."
)

_COCKPIT_LOCKED_NOTICE = (
    "**Live-Cockpit noch gesperrt:** Monitor und Manuelle Geräte erscheinen erst, "
    "wenn die Smarthome-Anbindung für den Live-Betrieb vollständig und korrekt "
    "konfiguriert ist. Prüfen Sie **Anbindung**, **Live-Lesen** und die "
    "Verbindungstests auf dieser Seite."
)


def _render_cockpit_locked_notice() -> None:
    """Explain why Live-Cockpit stays hidden after planning is ready."""
    if not needs_planning_onboarding():
        return
    if not is_planning_ready() or is_betrieb_unlocked():
        return
    st.info(_COCKPIT_LOCKED_NOTICE)


def _render_connection_section(backend: str) -> None:
    st.subheader("Anbindung")
    if backend == BACKEND_LOXONE:
        render_loxone_credentials_form(form_key="ehal_com_loxone_form")
    elif backend == BACKEND_HA:
        render_ha_connection_form(form_key="ehal_com_ha_form")
    elif backend == BACKEND_OPENEMS:
        render_openems_connection_form(form_key="ehal_com_openems_form")


def render() -> None:
    render_page_title_with_help(
        "🔗 EHAL-Com",
        _EHAL_COM_HELP,
        key="ehal_com_help",
        page_docs_key="ehal-com",
    )
    st.caption(f"Konfiguration: `{config.CONFIG.config_path}`")
    _render_cockpit_locked_notice()

    backend = render_backend_selector(key_prefix="ehal_com")
    _render_connection_section(backend)

    render_loxone_debug_block()

    if backend == BACKEND_HA:
        from ui.ehal_ha_mapping import render_ehal_ha_mapping_section

        with st.expander("HA Entity → EHAL Mapping", expanded=True):
            render_ehal_ha_mapping_section()

    if backend == BACKEND_LOXONE:
        from ui.ehal_efm_import import render_efm_consumer_import_section
        from ui.ehal_loxone_mapping import render_ehal_loxone_mapping_section

        st.caption(
            "Loxone → Hausprofil (**Loxone-Import**) liegt im "
            "**Hauskonfigurator** (Hausprofil, oberhalb von Verbraucher)."
        )

        st.subheader("Energieflussmonitor → Verbraucher")
        with st.expander("Zähler importieren (2.4.l)", expanded=False):
            render_efm_consumer_import_section()

        st.subheader("Loxone Struktur → EHAL Mapping")
        with st.expander("Mapping-Tabelle", expanded=True):
            render_ehal_loxone_mapping_section()
