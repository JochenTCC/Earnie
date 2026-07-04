"""Betriebsmodus-Auswahl in der Streamlit-Sidebar."""
from __future__ import annotations

import os

import streamlit as st

UI_MODE_KEYS = ("sunset2sunset", "historical", "backtesting")
UI_MODE_LABELS = {
    "sunset2sunset": "Sunset-2-Sunset",
    "historical": "Historischer Tag",
    "backtesting": "Backtesting",
}


def get_enabled_ui_modes() -> list[str]:
    """
    Aktivierte UI-Modi aus ENERGY_OPTIMIZER_UI_MODES
    (kommagetrennt: sunset2sunset,historical,backtesting).
    Ohne Variable: alle Modi (Entwicklung).
    """
    raw = os.environ.get("ENERGY_OPTIMIZER_UI_MODES", "").strip()
    if not raw:
        return [UI_MODE_LABELS[k] for k in UI_MODE_KEYS]
    requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
    enabled = [UI_MODE_LABELS[k] for k in UI_MODE_KEYS if k in requested]
    return enabled or [UI_MODE_LABELS["sunset2sunset"]]


def render_mode_selector() -> str:
    enabled_modes = get_enabled_ui_modes()
    raw = os.environ.get("ENERGY_OPTIMIZER_UI_MODES", "").strip()
    if raw and not any(
        part.strip().lower() in UI_MODE_LABELS
        for part in raw.split(",")
        if part.strip()
    ):
        st.sidebar.warning(
            "Ungültige ENERGY_OPTIMIZER_UI_MODES – verwende nur Sunset-2-Sunset."
        )

    if len(enabled_modes) == 1:
        mode = enabled_modes[0]
        st.session_state.app_mode = mode
        return mode

    st.sidebar.header("🕒 Betriebsmodus")
    default_idx = 0
    previous = st.session_state.get("app_mode")
    if previous in enabled_modes:
        default_idx = enabled_modes.index(previous)
    elif previous == "Echtzeit":
        s2_label = UI_MODE_LABELS["sunset2sunset"]
        if s2_label in enabled_modes:
            default_idx = enabled_modes.index(s2_label)

    help_parts = []
    if UI_MODE_LABELS["sunset2sunset"] in enabled_modes:
        help_parts.append(
            "Sunset-2-Sunset: Produktiv-Cockpit mit SA₀→SA₁ und SA₁→SA₂."
        )
    if UI_MODE_LABELS["historical"] in enabled_modes:
        help_parts.append("Historisch: beliebiger Tag aus den letzten 12 Monaten.")
    if UI_MODE_LABELS["backtesting"] in enabled_modes:
        help_parts.append(
            "Backtesting: Ergebnisse aus scripts/run_backtesting.py (backtesting_log.json)."
        )

    mode = st.sidebar.radio(
        "Optimierung für:",
        enabled_modes,
        index=default_idx,
        help=" ".join(help_parts) if help_parts else None,
    )
    st.session_state.app_mode = mode
    return mode
