"""Analyse Verbrauch & Kosten: Live-Log attribution plus Wärmeinhalt."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from ui.chart_context import live_now
from ui.consumer_cost_analysis_charts import render_window_analysis
from ui.consumer_cost_analysis_data import CostAnalysisSeries, build_cost_analysis_series
from ui.consumption_display.charts import live_heat_content_chart
from ui.consumption_display.heat_content_history import live_heat_content_for_window
from ui.consumption_display.navigation import render_period_navigation
from ui.consumption_display.period import PeriodKind, TimeWindow, format_window_label
from ui.help_hint import render_page_title_with_help

_HELP = (
    "Analyse aus dem Produktiv-Log: Verbrauch je Verbraucher vs. Preis/PV, "
    "Herkunft (PV / Batterie / Netz) und grobe Kosten nur für den Netzanteil. "
    "Charts für die letzten 7 oder 28 Tage (verschiebbar); Kennzahl zusätzlich "
    "für die letzten 365 Tage der vorhandenen Log-Daten — keine Rechnungskorrektur. "
    "Darunter Wärmeinhalt (Sim vs. Ist) aus Live `thermal_observability`."
)

_PERIOD_OPTIONS = {
    "7 Tage": PeriodKind.ROLLING_7,
    "28 Tage": PeriodKind.ROLLING_28,
}


def _select_analysis_window(timestamps: list[str]) -> TimeWindow | None:
    length_label = st.radio(
        "Zeitfenster",
        options=list(_PERIOD_OPTIONS.keys()),
        horizontal=True,
        key="cost_analysis_period_length",
    )
    period_kind = _PERIOD_OPTIONS[length_label]
    return render_period_navigation(
        timestamps,
        key_prefix="cost_analysis",
        period_kind=period_kind,
        reset_token="cost_analysis_v2",
        default_to_latest=True,
    )


def _render_cost_section(
    series: CostAnalysisSeries, window: TimeWindow, *, now: datetime
) -> None:
    render_window_analysis(series, window=window, now=now)


def _render_heat_content_section(window: TimeWindow) -> None:
    st.markdown("#### Wärmeinhalt")
    data = live_heat_content_for_window(window.start, window.end)
    if data is None:
        st.info(
            f"Keine Wärmeinhalt-Daten (Sim/Ist) in `optimization_history.jsonl` "
            f"für {format_window_label(window)}."
        )
        return
    fig = live_heat_content_chart(
        data.timestamps,
        q_sim_by_key=data.q_sim_by_key,
        q_meas_by_key=data.q_meas_by_key,
        labels=data.labels,
        title=f"Wärmeinhalt — {format_window_label(window)}",
    )
    if fig is None:
        st.info(
            f"Keine Wärmeinhalt-Daten (Sim/Ist) in `optimization_history.jsonl` "
            f"für {format_window_label(window)}."
        )
        return
    st.plotly_chart(fig, width="stretch")
    meta = fig.layout.meta or {}
    if not meta.get("has_measured"):
        st.caption(
            "Ist-Wärmeinhalt erscheint, sobald der Live-Dienst `T_eq` / Pool-Temperatur "
            "als `Q_meas` in `optimization_history.jsonl` aufzeichnet."
        )
    elif not meta.get("has_sim"):
        st.caption(
            "Sim-Wärmeinhalt (`Q_sim`) fehlt in diesem Fenster — nur Ist vorhanden."
        )


def render() -> None:
    render_page_title_with_help(
        "📈 Analyse Verbrauch & Kosten",
        _HELP,
        key="consumer_analysis_help",
        page_docs_key="consumer-analysis",
    )
    now = live_now()
    series = build_cost_analysis_series(now=now)
    if series is None or not series.slots:
        st.info("Noch keine Produktiv-Log-Daten für die Verbrauchs- & Kostenanalyse.")
        return

    timestamps = [slot.slot_start.isoformat() for slot in series.slots]
    selected = _select_analysis_window(timestamps)
    if selected is None:
        st.info("Keine Zeitfenster im Produktiv-Log.")
        return

    _render_cost_section(series, selected, now=now)
    st.divider()
    _render_heat_content_section(selected)
