"""Hauskonfigurator (Mockup): funktionsloser Platzhalter für Gebäude-Parameter."""
from __future__ import annotations

import streamlit as st

from ui.help_hint import render_page_title_with_help

_HELP = (
    "Geplant: Erfassung von Gebäude-/Thermik-Parametern (Energieausweis) für "
    "gekoppelte Wärmemodelle. Aktuell nur Mockup."
)


def render() -> None:
    render_page_title_with_help("🏠 Hauskonfigurator", _HELP, key="house_config_help")
    st.info("Geplant — der Hauskonfigurator wird in einem späteren Schritt umgesetzt.")

    col_a, col_b = st.columns(2)
    col_a.number_input("Wohnfläche (m²)", min_value=0.0, value=0.0, disabled=True)
    col_b.number_input("Heizlast (kW)", min_value=0.0, value=0.0, disabled=True)
    st.slider("Wärmedämmung", min_value=0, max_value=100, value=50, disabled=True)
