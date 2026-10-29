"""UI-Modus-Gating für die Menüstruktur (welche Seiten werden registriert)."""
from __future__ import annotations

import config
import streamlit as st
from runtime_store.env_vars import DEVICE_DETECTION_MODE, read_env

UI_MODE_KEYS = (
    "sunset2sunset",
    "scenario_explorer",
    "live_environment",
    "price_forecast",
    DEVICE_DETECTION_MODE,
)
UI_MODE_LABELS = {
    "sunset2sunset": "Sunset-2-Sunset",
    "scenario_explorer": "Szenario-Explorer",
    "live_environment": "Daemon Control",
    "price_forecast": "Preis-Prognose (Dev)",
    DEVICE_DETECTION_MODE: "Geräteerkennung (Dev)",
}


def _mode_keys_from_env(raw: str) -> list[str]:
    requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
    # device_detection has no page of its own; alone it must not empty the menu.
    if not requested - {DEVICE_DETECTION_MODE}:
        return ["sunset2sunset"] + ([DEVICE_DETECTION_MODE] if requested else [])
    enabled = [k for k in UI_MODE_KEYS if k in requested]
    return enabled or ["sunset2sunset"]


def get_enabled_ui_mode_keys() -> list[str]:
    """
    Aktivierte UI-Modus-Schlüssel aus EARNIE_UI_MODES
    (kommagetrennt: sunset2sunset,scenario_explorer,live_environment,price_forecast).
    ``device_detection`` (Dev) hat keine eigene Seite; es schaltet das Phasen-Log
    der Geräteerkennung im Daemon frei (``runtime_store.env_vars``).

    Ohne Env-Variable: Sunset-2-Sunset, Szenario-Explorer und Daemon Control;
    Preis-Prognose nur wenn ui.price_forecast_page_enabled in config.json true ist
    (Standard: false).
    """
    raw = read_env("UI_MODES")
    if raw:
        return _mode_keys_from_env(raw)
    keys = ["sunset2sunset", "scenario_explorer", "live_environment"]
    if config.get_ui_price_forecast_page_enabled():
        keys.append("price_forecast")
    return keys


def get_enabled_ui_modes() -> list[str]:
    """Anzeigenamen der aktiven Modi (Reihenfolge wie get_enabled_ui_mode_keys)."""
    return [UI_MODE_LABELS[k] for k in get_enabled_ui_mode_keys()]


def render_ui_mode_env_notices() -> None:
    """Zeigt Hinweise zu ungültigen/entfallenen EARNIE_UI_MODES-Werten."""
    raw = read_env("UI_MODES")
    if not raw:
        return
    requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
    if "historical" in requested:
        st.sidebar.info(
            "Modus „Historischer Tag“ entfällt — Nachrechnung folgt in Szenario-Explorer."
        )
    if "backtesting" in requested:
        st.sidebar.info(
            "Modus „Backtesting“ umbenannt — nutzen Sie "
            "`scenario_explorer` in EARNIE_UI_MODES."
        )
    if "scenario_exploration" in requested:
        st.sidebar.info(
            "Modus-Schlüssel `scenario_exploration` umbenannt — nutzen Sie "
            "`scenario_explorer` in EARNIE_UI_MODES."
        )
    if requested and not any(part in UI_MODE_LABELS for part in requested):
        st.sidebar.warning(
            "Ungültige EARNIE_UI_MODES – gültige Keys: "
            "sunset2sunset, scenario_explorer, live_environment, price_forecast."
        )
