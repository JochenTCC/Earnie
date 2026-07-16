"""Backtesting-Seite: wrappt ui/backtesting.py (Controls im Seiten-Body)."""
from __future__ import annotations

import streamlit as st

import config
from ui.backtesting import render_backtesting_block
from ui.help_hint import render_page_title_with_help

_BACKTESTING_HELP = (
    "Szenario-Explorer: Berechnung aus der Konfiguration starten und Ergebnisse auswerten "
    "(Referenz ohne Optimierung vs. optimierte Szenarien). "
    "Läuft offline via `scripts.run_backtesting`."
)

_RESULTS_DISCLAIMER = (
    "Ergebnisse sind Modellrechnungen. Es gibt keine Garantie, "
    "dass Live-Einsparungen exakt den Simulationen entsprechen "
    "(Wetter, Verhalten, Tarifdetails, Hardwaregrenzen)."
)


def render() -> None:
    render_page_title_with_help(
        "📊 Szenario-Explorer",
        _BACKTESTING_HELP,
        key="backtesting_scope_help",
    )
    st.info(_RESULTS_DISCLAIMER)
    st.caption(f"Konfiguration: `{config.CONFIG.config_path}`")
    render_backtesting_block()
