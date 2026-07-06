"""Betriebsmodus-Auswahl in der Streamlit-Sidebar."""
from __future__ import annotations

import os

import config
import streamlit as st

UI_MODE_KEYS = ("sunset2sunset", "backtesting", "price_forecast")
UI_MODE_LABELS = {
    "sunset2sunset": "Sunset-2-Sunset",
    "backtesting": "Backtesting",
    "price_forecast": "Preis-Prognose (Dev)",
}


def _modes_from_env(raw: str) -> list[str]:
    requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
    enabled = [UI_MODE_LABELS[k] for k in UI_MODE_KEYS if k in requested]
    return enabled or [UI_MODE_LABELS["sunset2sunset"]]


def get_enabled_ui_modes() -> list[str]:
    """
    Aktivierte UI-Modi aus ENERGY_OPTIMIZER_UI_MODES
    (kommagetrennt: sunset2sunset,backtesting,price_forecast).

    Ohne Env-Variable: Sunset-2-Sunset und Backtesting; Preis-Prognose nur wenn
    ui.price_forecast_page_enabled in config.json true ist (Standard: false).
    """
    raw = os.environ.get("ENERGY_OPTIMIZER_UI_MODES", "").strip()
    if raw:
        return _modes_from_env(raw)
    base_keys = ("sunset2sunset", "backtesting")
    if config.get_ui_price_forecast_page_enabled():
        base_keys = (*base_keys, "price_forecast")
    return [UI_MODE_LABELS[k] for k in base_keys]


def render_mode_selector() -> str:
    enabled_modes = get_enabled_ui_modes()
    raw = os.environ.get("ENERGY_OPTIMIZER_UI_MODES", "").strip()
    if raw:
        requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
        if "historical" in requested:
            st.sidebar.info(
                "Modus „Historischer Tag“ entfällt — Nachrechnung folgt im Backtesting."
            )
        if requested and not any(part in UI_MODE_LABELS for part in requested):
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
    elif previous in ("Echtzeit", "Historischer Tag"):
        s2_label = UI_MODE_LABELS["sunset2sunset"]
        if s2_label in enabled_modes:
            default_idx = enabled_modes.index(s2_label)

    help_parts = []
    if UI_MODE_LABELS["sunset2sunset"] in enabled_modes:
        help_parts.append(
            "Sunset-2-Sunset: Produktiv-Cockpit mit SA₀→SA₁ und SA₁→SA₂."
        )
    if UI_MODE_LABELS["backtesting"] in enabled_modes:
        help_parts.append(
            "Backtesting: Ergebnisse aus scripts/run_backtesting.py (backtesting_log.json)."
        )
    if UI_MODE_LABELS["price_forecast"] in enabled_modes:
        help_parts.append(
            "Preis-Prognose (Dev): OLS vs. Ist vs. Spiegelung auf Training-Datasets."
        )

    mode = st.sidebar.radio(
        "Optimierung für:",
        enabled_modes,
        index=default_idx,
        help=" ".join(help_parts) if help_parts else None,
    )
    st.session_state.app_mode = mode
    return mode
