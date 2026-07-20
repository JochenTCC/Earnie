"""Hauskonfigurator: Verbraucher, Jahresverbrauch, PV-Anlagen und Batterien."""
from __future__ import annotations

import streamlit as st

from ui.help_hint import render_page_title_with_help
from ui.house_config_profile_form import render_house_profile_tab
from ui.planning_battery_form import render_battery_planning_tab
from ui.planning_pv_form import render_pv_planning_tab

_HOUSE_CONFIG_TAB_KEY = "house_config_active_tab"
_HOUSE_CONFIG_TABS = ("Hausprofil", "PV-Anlagen", "Batterien")


def _help_text() -> str:
    return (
        "Backtesting-Planung: Hausprofil mit Verbrauchern, PV-Anlagen und Batterie-Entitäten. "
        "Szenarien und Live-Zuordnung (Tarife, Entitäts-Referenzen) in Szenarieneditor bzw. "
        "Live-Konfiguration. "
        "Grundlast = max(2 % Jahresverbrauch, Jahresverbrauch − Summe Verbraucher)."
    )


def render() -> None:
    render_page_title_with_help("🏠 Hauskonfigurator", _help_text(), key="house_config_help")

    if _HOUSE_CONFIG_TAB_KEY not in st.session_state:
        st.session_state[_HOUSE_CONFIG_TAB_KEY] = _HOUSE_CONFIG_TABS[0]
    active = st.segmented_control(
        "Bereich",
        options=list(_HOUSE_CONFIG_TABS),
        key=_HOUSE_CONFIG_TAB_KEY,
        label_visibility="collapsed",
    )
    if active not in _HOUSE_CONFIG_TABS:
        active = _HOUSE_CONFIG_TABS[0]
        st.session_state[_HOUSE_CONFIG_TAB_KEY] = active

    if active == "Hausprofil":
        render_house_profile_tab()
    elif active == "PV-Anlagen":
        render_pv_planning_tab()
    else:
        render_battery_planning_tab()
