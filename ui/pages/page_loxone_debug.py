"""EHAL-Com: Debug-Seite für Live-Lesen, Live-Schreiben und Signalliste."""
from __future__ import annotations

import streamlit as st

from runtime_store.ehal_setup import (
    BACKEND_HA,
    BACKEND_LOXONE,
    active_ehal_backend,
)
from ui.help_hint import render_page_title_with_help
from ui.loxone_debug import render_loxone_debug_block
from ui.setup_readiness import (
    is_betrieb_unlocked,
    is_planning_ready,
    needs_planning_onboarding,
)

_EHAL_COM_HELP = (
    "Live-Übersicht für Loxone, Home Assistant (EHAL) oder OpenEMS. "
    "Zugangsdaten und Backend-Wechsel liegen auf **Smarthome-Backend**. "
    "Live-Lesen zeigt `sens_*`/`get_*` mit EHAL-Feld und Push-Status; "
    "Live-Schreiben die Schreibvorgänge (`set_*`, Flex-Freigabe/`set_enable`) "
    "aus dem Produktiv-Lauf von main.py. "
    "**Schreibtest** prüft Publish + Callback "
    "(nur bei ausgeschaltetem Silent-Modus). "
    "Die **Signalliste** zeigt den Vertrag (qualifizierte IDs, Pflicht/optional, "
    "Match-Status, Export) für alle Backends — kein Entity-Mapping mehr. "
    "Außerplanmäßige Optimierung: Earnie_Request_Optimize (Port 8541)."
)

_COCKPIT_LOCKED_NOTICE = (
    "**Live-Cockpit noch gesperrt:** Monitor und Manuelle Geräte erscheinen erst, "
    "wenn die Smarthome-Anbindung für den Live-Betrieb vollständig und korrekt "
    "konfiguriert ist. Prüfen Sie **Smarthome-Backend** (Anbindung), **Live-Lesen** "
    "und die Verbindungstests auf dieser Seite."
)


def _render_cockpit_locked_notice() -> None:
    """Explain why Live-Cockpit stays hidden after planning is ready."""
    if not needs_planning_onboarding():
        return
    if not is_planning_ready() or is_betrieb_unlocked():
        return
    st.info(_COCKPIT_LOCKED_NOTICE)


def _render_live_topology_status() -> None:
    """Refuse-style error when Topology P1 live rules fail (not warn-only)."""
    from house_config.topology_live import validate_live_topology_from_config_dir

    try:
        validate_live_topology_from_config_dir()
    except ValueError as exc:
        st.error(f"Live-Topologie abgelehnt: {exc}")
    except Exception as exc:  # noqa: BLE001 — sidecars may be absent in setup
        st.warning(f"Live-Topologie nicht prüfbar: {exc}")


def render() -> None:
    import config

    render_page_title_with_help(
        "🔗 EHAL-Com",
        _EHAL_COM_HELP,
        key="ehal_com_help",
        page_docs_key="ehal-com",
    )
    st.caption(f"Konfiguration: `{config.CONFIG.config_path}`")
    _render_cockpit_locked_notice()
    _render_live_topology_status()

    backend = active_ehal_backend()
    st.caption(
        "Zugangsdaten und Backend-Wechsel auf **Smarthome-Backend**. "
        "Diese Seite zeigt Live-Lesen/Schreiben und die Signalliste."
    )
    if backend == BACKEND_LOXONE:
        from runtime_store.loxone_callback_status import format_loxone_callback_caption

        st.caption(format_loxone_callback_caption())

    render_loxone_debug_block()

    if backend == BACKEND_HA:
        from ui.ha_carrier_download import render_ha_carrier_yaml_download

        st.subheader("HA Push-Carrier")
        with st.expander("YAML-Paket (ENTITY_* · periodischer Push)", expanded=True):
            render_ha_carrier_yaml_download()

    if backend == BACKEND_LOXONE:
        st.caption(
            "Loxone → Hausprofil (**Loxone-Import**) liegt auf "
            "**Smarthome-Backend** (nach erfolgreicher Verbindung)."
        )

    from ui.ehal_signal_list import render_ehal_signal_list_section

    st.subheader("Signalliste")
    with st.expander("Vertrag (EHAL-IDs · Match · Export)", expanded=True):
        render_ehal_signal_list_section()
