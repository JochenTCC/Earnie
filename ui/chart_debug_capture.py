"""Streamlit-Steuerung: Debug-Dump-ZIP (Chart oder Prod) speichern."""
from __future__ import annotations

import logging
from typing import Any

import streamlit as st

import config
from integrations import loxone_client
from runtime_store.chart_debug_capture import (
    build_chart_section,
    read_zip_bytes,
)
from runtime_store.debug_dump_archive import (
    DUMP_TYPE_CHART,
    DUMP_TYPE_PROD,
    write_debug_dump_zip,
)
from ui.charts import build_power_soc_chart_figure
from ui.history_navigation import get_s2_cycle_offset, get_s2_segment_index
from ui.simulation_results import SESSION_LIVE_DISPLAY_BUNDLE

logger = logging.getLogger("app")

_SESSION_LAST_CAPTURE_PATH = "chart_debug_last_capture_path"
_DUMP_TYPE_LABELS = {
    "Chart (UI/Anzeige)": DUMP_TYPE_CHART,
    "Prod (Optimizer/Domain)": DUMP_TYPE_PROD,
}


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
        logger.warning("Debug-Dump: Plotly Chart 1 konnte nicht serialisiert werden: %s", exc)
        return None


def _save_chart_dump(bundle, current_soc: float | None, live_power: dict[str, Any] | None) -> str:
    capture_live_power = live_power
    if capture_live_power is None:
        capture_live_power = loxone_client.fetch_loxone_live_power()
    chart_payload = build_chart_section(
        bundle,
        current_soc=current_soc,
        live_power=capture_live_power,
        session_meta=_session_meta(),
        chart1_plotly_json=_chart1_plotly_json(bundle),
    )
    chart_context = bundle.chart_context
    chart_window = chart_context.chart_window if chart_context else None
    return write_debug_dump_zip(
        DUMP_TYPE_CHART,
        chart_payload=chart_payload,
        chart_window_start=chart_window.start if chart_window else None,
        chart_window_end=chart_window.end if chart_window else None,
    )


def _save_prod_dump(*, title: str, symptom: str) -> str:
    return write_debug_dump_zip(
        DUMP_TYPE_PROD,
        title=title.strip(),
        symptom=symptom.strip(),
    )


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
    st.caption(
        "Debug-Dump: Chart- oder Prod-Archiv als ZIP sichern "
        "(config.json, `runtime/local_settings.json` oder `EARNIE_UI_CHART_DEBUG_CAPTURE_ENABLED=1`)."
    )
    type_label = st.selectbox(
        "Dump-Typ",
        options=list(_DUMP_TYPE_LABELS.keys()),
        key="debug_dump_type_select",
    )
    dump_type = _DUMP_TYPE_LABELS[type_label]

    title = ""
    symptom = ""
    if dump_type == DUMP_TYPE_PROD:
        title = st.text_input("Titel (optional)", key="debug_dump_prod_title", value="")
        symptom = st.text_area("Symptom (optional)", key="debug_dump_prod_symptom", value="")

    can_save_chart = dump_type == DUMP_TYPE_CHART and bundle is not None
    can_save_prod = dump_type == DUMP_TYPE_PROD
    if dump_type == DUMP_TYPE_CHART and bundle is None:
        st.info("Chart-Dump benötigt die aktuelle Live-Anzeige (Bundle fehlt).")

    if st.button("Debug-Dump speichern", key="chart_debug_capture_btn"):
        if dump_type == DUMP_TYPE_CHART and not can_save_chart:
            st.error("Chart-Dump nicht möglich: Live-Anzeige fehlt.")
            return
        if dump_type == DUMP_TYPE_PROD and not can_save_prod:
            st.error("Prod-Dump nicht möglich.")
            return
        try:
            if dump_type == DUMP_TYPE_CHART:
                zip_path = _save_chart_dump(bundle, current_soc, live_power)
            else:
                zip_path = _save_prod_dump(title=title, symptom=symptom)
            st.session_state[_SESSION_LAST_CAPTURE_PATH] = zip_path
            st.success(f"Debug-Dump gespeichert: `{zip_path}`")
        except (OSError, FileNotFoundError, ValueError) as exc:
            st.error(f"Debug-Dump konnte nicht gespeichert werden: {exc}")
            logger.exception("Debug-Dump-Speichern fehlgeschlagen")

    zip_path = st.session_state.get(_SESSION_LAST_CAPTURE_PATH)
    if zip_path:
        try:
            st.download_button(
                label="Debug-Dump ZIP herunterladen",
                data=read_zip_bytes(zip_path),
                file_name=zip_path.split("/")[-1].split("\\")[-1],
                mime="application/zip",
                key="chart_debug_download_btn",
            )
        except OSError:
            st.session_state.pop(_SESSION_LAST_CAPTURE_PATH, None)
