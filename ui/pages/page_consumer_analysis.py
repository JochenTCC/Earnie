"""Analyse Verbrauch & Kosten: Live-Log attribution plus Swimspa section."""
from __future__ import annotations

import streamlit as st

from ui.chart_context import live_now
from ui.consumer_analysis_charts import (
    render_swimspa_filter_chart,
    render_swimspa_temperature_chart,
)
from ui.consumer_analysis_data import build_swimspa_analysis_data
from ui.consumer_cost_analysis_charts import render_window_analysis
from ui.consumer_cost_analysis_data import build_cost_analysis_series
from ui.consumption_display.navigation import render_period_navigation
from ui.consumption_display.period import PeriodKind
from ui.help_hint import render_page_title_with_help
from ui.history_navigation import get_s2_cycle_offset, get_s2_segment_index

_HELP = (
    "Analyse aus dem Produktiv-Log: Verbrauch je Verbraucher vs. Preis/PV, "
    "Herkunft (PV / Batterie / Netz) und grobe Kosten nur für den Netzanteil. "
    "Charts für die letzten 7 oder 28 Tage (verschiebbar); Kennzahl zusätzlich "
    "für die letzten 365 Tage der vorhandenen Log-Daten — keine Rechnungskorrektur. "
    "Swimspa-Temperatur und Filter unten."
)

_PERIOD_OPTIONS = {
    "7 Tage": PeriodKind.ROLLING_7,
    "28 Tage": PeriodKind.ROLLING_28,
}


def _render_cost_section() -> None:
    now = live_now()
    series = build_cost_analysis_series(now=now)
    if series is None or not series.slots:
        st.info("Noch keine Produktiv-Log-Daten für die Verbrauchs- & Kostenanalyse.")
        return

    timestamps = [slot.slot_start.isoformat() for slot in series.slots]
    length_label = st.radio(
        "Zeitfenster",
        options=list(_PERIOD_OPTIONS.keys()),
        horizontal=True,
        key="cost_analysis_period_length",
    )
    period_kind = _PERIOD_OPTIONS[length_label]
    selected = render_period_navigation(
        timestamps,
        key_prefix="cost_analysis",
        period_kind=period_kind,
        reset_token="cost_analysis_v2",
        default_to_latest=True,
    )
    if selected is None:
        st.info("Keine Zeitfenster im Produktiv-Log.")
        return
    render_window_analysis(series, window=selected, now=now)


def _render_swimspa_section() -> None:
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


def render() -> None:
    render_page_title_with_help(
        "📈 Analyse Verbrauch & Kosten",
        _HELP,
        key="consumer_analysis_help",
        page_docs_key="consumer-analysis",
    )
    _render_cost_section()
    st.divider()
    _render_swimspa_section()
