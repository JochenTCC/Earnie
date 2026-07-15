"""Streamlit-Steuerung: Chart-Debug-ZIP bei Verdachtsfall speichern."""
from __future__ import annotations

import logging
from typing import Any

import streamlit as st

import config
from integrations import loxone_client
from runtime_store.chart_debug_capture import read_zip_bytes, write_capture_zip
from ui.charts import build_power_soc_chart_figure
from ui.history_navigation import get_s2_cycle_offset, get_s2_segment_index
from ui.simulation_results import SESSION_LIVE_DISPLAY_BUNDLE

logger = logging.getLogger("app")

_SESSION_LAST_CAPTURE_PATH = "chart_debug_last_capture_path"


def _session_meta() -> dict[str, Any]:
    return {
        "live_optimization_cache_key": st.session_state.get("live_optimization_cache_key"),
        "s2_cycle_offset": get_s2_cycle_offset(),
        "s2_segment_index": get_s2_segment_index(),
    }


def _chart1_plotly_json(bundle) -> str | None:
    try:
        fig = build_power_soc_chart_figure(
            bundle.display_df,
            bundle.baseline_df,
            bundle.display_matched,
            chart_window=(
                bundle.chart_context.chart_window if bundle.chart_context else None
            ),
            chart_zones=bundle.chart_zones,
            sun_markers=bundle.sun_markers,
            slot_qualities=bundle.chart_qualities,
            history_slot_count=bundle.history_slot_count,
            chart_header_label=bundle.chart_header_label,
            slot_deviation_events=bundle.slot_deviation_events,
            optimization_matrix=bundle.optimization_matrix,
        )
        return fig.to_json()
    except Exception as exc:
        logger.warning("Chart-Debug: Plotly Chart 1 konnte nicht serialisiert werden: %s", exc)
        return None


def render_chart_debug_capture_controls(
    current_soc: float | None,
    live_power: dict[str, Any] | None = None,
) -> None:
    """
    Zeigt Speichern-Button und Download, wenn ui.chart_debug_capture_enabled gesetzt ist.
    """
    if not config.get_ui_chart_debug_capture_enabled():
        return
    bundle = st.session_state.get(SESSION_LIVE_DISPLAY_BUNDLE)
    if bundle is None:
        return

    st.caption(
        "Chart-Debug: Plot-Quelldaten als ZIP sichern "
        "(config.json, `runtime/local_settings.json` oder `EARNIE_UI_CHART_DEBUG_CAPTURE_ENABLED=1`)."
    )
    if st.button("Chart-Debug speichern", key="chart_debug_capture_btn"):
        try:
            capture_live_power = live_power
            if capture_live_power is None:
                capture_live_power = loxone_client.fetch_loxone_live_power()
            zip_path = write_capture_zip(
                bundle,
                current_soc=current_soc,
                live_power=capture_live_power,
                session_meta=_session_meta(),
                chart1_plotly_json=_chart1_plotly_json(bundle),
            )
            st.session_state[_SESSION_LAST_CAPTURE_PATH] = zip_path
            st.success(f"Chart-Debug gespeichert: `{zip_path}`")
        except OSError as exc:
            st.error(f"Chart-Debug konnte nicht gespeichert werden: {exc}")
            logger.exception("Chart-Debug-Speichern fehlgeschlagen")

    zip_path = st.session_state.get(_SESSION_LAST_CAPTURE_PATH)
    if zip_path:
        try:
            st.download_button(
                label="Chart-Debug ZIP herunterladen",
                data=read_zip_bytes(zip_path),
                file_name=zip_path.split("/")[-1].split("\\")[-1],
                mime="application/zip",
                key="chart_debug_download_btn",
            )
        except OSError:
            st.session_state.pop(_SESSION_LAST_CAPTURE_PATH, None)
