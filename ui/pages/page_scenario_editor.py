"""Szenarieneditor (Mockup): funktionsloser Platzhalter für Backtesting-Szenarien."""
from __future__ import annotations

import streamlit as st

from ui.help_hint import render_page_title_with_help

_HELP = "Geplant: grafischer Editor für Backtesting-Szenarien. Aktuell nur Mockup."


def render() -> None:
    render_page_title_with_help("🧪 Szenarieneditor", _HELP, key="scenario_editor_help")
    st.info("Geplant — der Szenarieneditor wird in einem späteren Schritt umgesetzt.")

    st.text_input("Szenario-Name", value="", disabled=True)
    col_a, col_b = st.columns(2)
    col_a.number_input("PV kWp", min_value=0.0, value=0.0, disabled=True)
    col_b.number_input("Batterie kWh", min_value=0.0, value=0.0, disabled=True)
    st.button("Szenario speichern", disabled=True)
