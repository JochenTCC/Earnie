"""Manuelle Geräte (Mockup): Empfehlungsmodus folgt in einem späteren Schritt."""
from __future__ import annotations

import streamlit as st

from ui.help_hint import render_page_title_with_help

_DEVICES_HELP = (
    "Geplant: Empfehlungsmodus für manuelle Geräte (Waschmaschine, Trockner, "
    "Geschirrspüler) — günstigste Startzeit im 6-h-Horizont. Aktuell nur Mockup."
)
_DEVICES = ("Waschmaschine", "Trockner", "Geschirrspüler")


def render() -> None:
    render_page_title_with_help(
        "🔌 Manuelle Geräte", _DEVICES_HELP, key="devices_scope_help"
    )
    st.info("Geplant — der Empfehlungsmodus wird in einem späteren Schritt umgesetzt.")

    for device in _DEVICES:
        st.markdown(f"#### {device}")
        col_power, col_runtime, col_action = st.columns([1, 1, 1])
        col_power.number_input(
            "Leistung (kW)", min_value=0.0, value=0.0, step=0.1, key=f"mock_power_{device}",
            disabled=True,
        )
        col_runtime.number_input(
            "Laufzeit (h)", min_value=0.0, value=0.0, step=0.25, key=f"mock_runtime_{device}",
            disabled=True,
        )
        col_action.button(
            "Günstigste Startzeit", key=f"mock_start_{device}", disabled=True
        )
