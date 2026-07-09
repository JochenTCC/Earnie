"""Hauskonfigurator: Verbraucher, Jahresverbrauch und PV-Anlage."""
from __future__ import annotations

import streamlit as st

from ui.help_hint import render_page_title_with_help
from ui.house_config_profile_form import render_house_profile_tab
from ui.planning_pv_form import render_pv_planning_tab


def _help_text() -> str:
    return (
        "Backtesting-Planung: Hausprofil mit Verbrauchern und PV-Anlage. "
        "Batterie und Tarife konfigurierst du im Szenarieneditor unter Runtime. "
        "Grundlast = max(5 % Jahresverbrauch, Jahresverbrauch − Summe Verbraucher)."
    )


def render() -> None:
    render_page_title_with_help("🏠 Hauskonfigurator", _help_text(), key="house_config_help")

    tab_profile, tab_pv = st.tabs(["Hausprofil", "PV-Anlage"])
    with tab_profile:
        render_house_profile_tab()
    with tab_pv:
        render_pv_planning_tab()
