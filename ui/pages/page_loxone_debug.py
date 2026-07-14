"""Loxone-Kommunikation: Debug-Seite für Live-Lesen und Schreib-Nachverfolgung."""
from __future__ import annotations

import streamlit as st

import config
from ui.help_hint import render_page_title_with_help
from ui.loxone_debug import render_loxone_debug_block

_LOXONE_DEBUG_HELP = (
    "Live-Übersicht aller konfigurierten Loxone-Merker (Lesen) und der letzten "
    "Schreibvorgänge aus dem Produktiv-Lauf von main.py. Im Silent-Modus werden "
    "nur Sollwerte angezeigt, keine tatsächlichen Schreibbestätigungen."
)


def render() -> None:
    render_page_title_with_help(
        "🔗 Loxone-Kommunikation",
        _LOXONE_DEBUG_HELP,
        key="loxone_debug_help",
    )
    st.caption(f"Konfiguration: `{config.CONFIG.config_path}`")
    render_loxone_debug_block()
