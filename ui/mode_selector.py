"""UI-Modus-Gating für die Menüstruktur (welche Seiten werden registriert)."""
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


def _mode_keys_from_env(raw: str) -> list[str]:
    requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
    enabled = [k for k in UI_MODE_KEYS if k in requested]
    return enabled or ["sunset2sunset"]


def get_enabled_ui_mode_keys() -> list[str]:
    """
    Aktivierte UI-Modus-Schlüssel aus ENERGY_OPTIMIZER_UI_MODES
    (kommagetrennt: sunset2sunset,backtesting,price_forecast).

    Ohne Env-Variable: Sunset-2-Sunset und Backtesting; Preis-Prognose nur wenn
    ui.price_forecast_page_enabled in config.json true ist (Standard: false).
    """
    raw = os.environ.get("ENERGY_OPTIMIZER_UI_MODES", "").strip()
    if raw:
        return _mode_keys_from_env(raw)
    keys = ["sunset2sunset", "backtesting"]
    if config.get_ui_price_forecast_page_enabled():
        keys.append("price_forecast")
    return keys


def get_enabled_ui_modes() -> list[str]:
    """Anzeigenamen der aktiven Modi (Reihenfolge wie get_enabled_ui_mode_keys)."""
    return [UI_MODE_LABELS[k] for k in get_enabled_ui_mode_keys()]


def render_ui_mode_env_notices() -> None:
    """Zeigt Hinweise zu ungültigen/entfallenen ENERGY_OPTIMIZER_UI_MODES-Werten."""
    raw = os.environ.get("ENERGY_OPTIMIZER_UI_MODES", "").strip()
    if not raw:
        return
    requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
    if "historical" in requested:
        st.sidebar.info(
            "Modus „Historischer Tag“ entfällt — Nachrechnung folgt im Backtesting."
        )
    if requested and not any(part in UI_MODE_LABELS for part in requested):
        st.sidebar.warning(
            "Ungültige ENERGY_OPTIMIZER_UI_MODES – verwende nur Sunset-2-Sunset."
        )
