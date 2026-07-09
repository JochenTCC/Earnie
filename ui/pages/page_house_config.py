"""Hauskonfigurator: Verbraucher, Jahresverbrauch und Planungs-Entitäten."""
from __future__ import annotations

import streamlit as st

from ui.help_hint import render_page_title_with_help
from ui.house_config_profile_form import render_house_profile_tab
from ui.planning_battery_form import render_battery_planning_tab
from ui.planning_pv_form import render_pv_planning_tab
from ui.house_config_io import tariffs_json_path
from ui.planning_tariff_form import render_tariff_selection_tab


def _help_text() -> str:
    return (
        "Backtesting-Planung: Hausprofil, PV-Anlage, Batterie und Tarifwahl. "
        "Grundlast = max(5 % Jahresverbrauch, Jahresverbrauch − Summe Verbraucher). "
        f"Tarif-Katalog: `{tariffs_json_path()}` (Auswahl nur, kein Editor)."
    )


def render() -> None:
    render_page_title_with_help("🏠 Hauskonfigurator", _help_text(), key="house_config_help")

    tab_profile, tab_pv, tab_battery, tab_tariffs = st.tabs(
        ["Hausprofil", "PV-Anlage", "Batterie", "Tarife"]
    )
    with tab_profile:
        render_house_profile_tab()
    with tab_pv:
        render_pv_planning_tab()
    with tab_battery:
        render_battery_planning_tab()
    with tab_tariffs:
        render_tariff_selection_tab()
