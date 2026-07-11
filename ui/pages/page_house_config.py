"""Hauskonfigurator: Verbraucher, Jahresverbrauch, PV-Anlage und Batterien."""
from __future__ import annotations

import streamlit as st

from ui.help_hint import render_page_title_with_help
from ui.house_config_profile_form import render_house_profile_tab
from ui.planning_battery_form import render_battery_planning_tab
from ui.planning_pv_form import render_pv_planning_tab


def _help_text() -> str:
    return (
        "Backtesting-Planung: Hausprofil mit Verbrauchern, PV-Anlage und Batterie-Entitäten. "
        "Szenarien und Live-Zuordnung (Tarife, Entitäts-Referenzen) in Szenarieneditor bzw. "
        "Echtzeit-Umgebung. "
        "Grundlast = max(5 % Jahresverbrauch, Jahresverbrauch − Summe Verbraucher)."
    )


def render() -> None:
    render_page_title_with_help("🏠 Hauskonfigurator", _help_text(), key="house_config_help")

    tab_profile, tab_pv, tab_battery = st.tabs(["Hausprofil", "PV-Anlage", "Batterien"])
    with tab_profile:
        render_house_profile_tab()
    with tab_pv:
        render_pv_planning_tab()
    with tab_battery:
        render_battery_planning_tab()
