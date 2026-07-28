"""Loxone-Com: Debug-Seite für Live-Lesen und Live-Schreiben."""
from __future__ import annotations

import streamlit as st

import config
from ui.help_hint import render_page_title_with_help
from ui.loxone_debug import render_loxone_debug_block
from ui.loxone_marker_forms import render_marker_config_editors
from ui.setup_readiness import (
    is_betrieb_unlocked,
    is_planning_ready,
    needs_planning_onboarding,
)

_LOXONE_DEBUG_HELP = (
    "Live-Übersicht aller konfigurierten Smarthome-Merker (Lesen) und der letzten "
    "Schreibvorgänge aus dem Produktiv-Lauf von main.py. Im Silent-Modus werden "
    "nur Sollwerte angezeigt, keine tatsächlichen Schreibbestätigungen. "
    "Anlagen-Merker und Event-Trigger können auf dieser Seite bearbeitet werden."
)

_COCKPIT_LOCKED_NOTICE = (
    "**Live-Cockpit noch gesperrt:** Monitor und Manuelle Geräte erscheinen erst, "
    "wenn die Smarthome-Merker für den Live-Betrieb vollständig und korrekt "
    "konfiguriert sind (`loxone_blocks` in `config.json` sowie Verbraucher-Merker "
    "im Hausprofil). Prüfen Sie die Tabelle **Live-Lesen** und den Button "
    "**Smarthome-Merker testen** — fehlerhafte oder Platzhalter-Namen halten das "
    "Live-Cockpit bewusst zurück."
)


def _render_cockpit_locked_notice() -> None:
    """Explain why Live-Cockpit stays hidden after planning is ready."""
    if not needs_planning_onboarding():
        return
    if not is_planning_ready() or is_betrieb_unlocked():
        return
    st.info(_COCKPIT_LOCKED_NOTICE)


def render() -> None:
    render_page_title_with_help(
        "🔗 Loxone-Com",
        _LOXONE_DEBUG_HELP,
        key="loxone_debug_help",
        page_docs_key="loxone-debug",
    )
    st.caption(f"Konfiguration: `{config.CONFIG.config_path}`")
    _render_cockpit_locked_notice()
    render_loxone_debug_block()
    from ui.ehal_ha_mapping import render_ehal_ha_mapping_section

    with st.expander("HA Entity → EHAL Mapping (2.4.c)", expanded=config.is_ehal_ha_backend()):
        render_ehal_ha_mapping_section()
    render_marker_config_editors()
