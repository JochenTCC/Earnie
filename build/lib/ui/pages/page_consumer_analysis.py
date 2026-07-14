"""Verbraucheranalyse: Swimspa Temperatur und Filter-Verbrauch."""
from __future__ import annotations

import streamlit as st

from ui.consumer_analysis_charts import (
    render_swimspa_filter_chart,
    render_swimspa_temperature_chart,
)
from ui.consumer_analysis_data import build_swimspa_analysis_data
from ui.help_hint import render_page_title_with_help
from ui.history_navigation import get_s2_cycle_offset, get_s2_segment_index

_HELP = (
    "Swimspa-Analyse aus dem Produktiv-Log: Ist-/Soll-Temperatur und "
    "Filter-Leistung (autonom vs. Earnie-initiiert). Nutzt dasselbe "
    "S-2-Zeitfenster wie das Cockpit."
)


def render() -> None:
    render_page_title_with_help(
        "📈 Verbraucheranalyse", _HELP, key="consumer_analysis_help"
    )
    st.markdown("#### Swimspa")
    data = build_swimspa_analysis_data(
        cycle_offset=get_s2_cycle_offset(),
        segment_index=get_s2_segment_index(),
    )
    if data is None:
        st.info(
            "Für dieses S-2-Segment liegen keine Historien-Daten vor "
            "(SA₁→SA₂ zeigt nur MILP-Prognose)."
        )
        return
    if data.gap_notice:
        st.caption(data.gap_notice)
    render_swimspa_temperature_chart(data.temperature_df, chart_zones=data.zones)
    render_swimspa_filter_chart(data.filter_df, chart_zones=data.zones)
