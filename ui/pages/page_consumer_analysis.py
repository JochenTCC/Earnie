"""Verbraucheranalyse (Mockup): Platzhalter inkl. Adaptionsalgorithmus."""
from __future__ import annotations

import streamlit as st

from ui.help_hint import render_page_title_with_help

_HELP = (
    "Geplant: Analyse des tatsächlichen Verbraucher-Verhaltens inkl. "
    "Adaptionsalgorithmus. Aktuell nur Mockup."
)


def render() -> None:
    render_page_title_with_help(
        "📈 Verbraucheranalyse", _HELP, key="consumer_analysis_help"
    )
    st.info("Geplant — die Verbraucheranalyse wird in einem späteren Schritt umgesetzt.")

    st.selectbox("Verbraucher", ["(keine Daten)"], disabled=True)
    st.checkbox("Adaptionsalgorithmus anzeigen", value=False, disabled=True)
    st.empty()
