"""Streamlit-Steuerung: Debug-Dump-ZIP speichern."""
from __future__ import annotations

import base64
import logging
from typing import Any

import streamlit as st

import config
from integrations import loxone_client
from runtime_store.chart_debug_capture import (
    build_chart_section,
    read_zip_bytes,
)
from runtime_store.debug_dump_archive import write_debug_dump_zip
from ui.charts import build_power_soc_chart_figure
from ui.history_navigation import get_s2_cycle_offset, get_s2_segment_index
from ui.simulation_results import SESSION_LIVE_DISPLAY_BUNDLE

logger = logging.getLogger("app")

_SESSION_LAST_CAPTURE_PATH = "chart_debug_last_capture_path"
_SESSION_META_PROMPT = "chart_debug_meta_prompt"
_SESSION_SAVE_MESSAGE = "chart_debug_save_message"
_SESSION_AUTO_DOWNLOAD = "chart_debug_auto_download"


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


def _save_debug_dump(
    bundle,
    current_soc: float | None,
    live_power: dict[str, Any] | None,
    *,
    title: str,
    symptom: str,
) -> str:
    chart_payload = None
    if bundle is not None:
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
    return write_debug_dump_zip(
        chart_payload=chart_payload,
        title=title.strip(),
        symptom=symptom.strip(),
    )


def _zip_file_name(zip_path: str) -> str:
    return zip_path.split("/")[-1].split("\\")[-1]


def _trigger_browser_download(data: bytes, file_name: str) -> None:
    """Start download in the main document (st.html is not iframed)."""
    b64 = base64.b64encode(data).decode("ascii")
    safe_name = (
        file_name.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "").replace("\r", "")
    )
    st.html(
        f"""
        <script>
        (function() {{
          const a = document.createElement('a');
          a.href = 'data:application/zip;base64,{b64}';
          a.download = '{safe_name}';
          document.body.appendChild(a);
          a.click();
          a.remove();
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def _close_dialog() -> None:
    st.session_state[_SESSION_META_PROMPT] = False
    st.session_state.pop(_SESSION_AUTO_DOWNLOAD, None)


def _finish_save(
    zip_path: str,
    *,
    start_download: bool,
) -> None:
    """Persist result, close dialog, optional auto-download on next main-page render."""
    st.session_state[_SESSION_LAST_CAPTURE_PATH] = zip_path
    st.session_state[_SESSION_META_PROMPT] = False
    st.session_state[_SESSION_SAVE_MESSAGE] = (
        "ok",
        f"Debug-Dump gespeichert: `{zip_path}`",
    )
    if start_download:
        st.session_state[_SESSION_AUTO_DOWNLOAD] = zip_path
    else:
        st.session_state.pop(_SESSION_AUTO_DOWNLOAD, None)
    st.rerun()


@st.dialog("Debug-Dump")
def _debug_dump_meta_dialog(
    bundle,
    current_soc: float | None,
    live_power: dict[str, Any] | None,
) -> None:
    st.caption("Titel und Symptom sind optional und landen in manifest.meta.")
    st.text_input("Titel (optional)", key="debug_dump_title")
    st.text_area("Symptom (optional)", key="debug_dump_symptom")
    col_create, col_download = st.columns(2)
    with col_create:
        create_only = st.button("ZIP erstellen", key="chart_debug_confirm_btn")
    with col_download:
        # Same pattern as create_only (closes dialog). Download runs on main page via st.html.
        create_and_download = st.button(
            "ZIP erstellen und herunterladen",
            type="primary",
            key="chart_debug_confirm_download_btn",
        )
    if st.button("Abbrechen", key="chart_debug_cancel_btn"):
        _close_dialog()
        st.rerun()
    if not create_only and not create_and_download:
        return

    title = str(st.session_state.get("debug_dump_title") or "")
    symptom = str(st.session_state.get("debug_dump_symptom") or "")
    try:
        zip_path = _save_debug_dump(
            bundle,
            current_soc,
            live_power,
            title=title,
            symptom=symptom,
        )
        _finish_save(zip_path, start_download=bool(create_and_download))
    except (OSError, FileNotFoundError, ValueError) as exc:
        logger.exception("Debug-Dump-Speichern fehlgeschlagen")
        st.error(f"Debug-Dump konnte nicht gespeichert werden: {exc}")


def render_chart_debug_capture_controls(
    current_soc: float | None,
    live_power: dict[str, Any] | None = None,
) -> None:
    """
    Zeigt Speichern-Button, wenn ui.chart_debug_capture_enabled gesetzt ist.

    Dialog speichert und schließt per st.rerun(); optionaler Download danach
    über st.html (Haupt-DOM, kein iframe).
    """
    if not config.get_ui_chart_debug_capture_enabled():
        return

    bundle = st.session_state.get(SESSION_LIVE_DISPLAY_BUNDLE)
    st.caption(
        "Debug-Dump: Archiv als ZIP sichern (volle Historie, optional Chart-Payload; "
        "config.json, `runtime/local_settings.json` oder "
        "`EARNIE_UI_CHART_DEBUG_CAPTURE_ENABLED=1`)."
    )
    if bundle is None:
        st.info("Ohne Live-Anzeige: Dump ohne Chart-Payload (nur Historie/Inputs).")

    save_message = st.session_state.pop(_SESSION_SAVE_MESSAGE, None)
    if isinstance(save_message, tuple) and len(save_message) == 2:
        kind, text = save_message
        if kind == "ok":
            st.success(text)
        else:
            st.error(text)

    auto_path = st.session_state.pop(_SESSION_AUTO_DOWNLOAD, None)
    if auto_path:
        try:
            _trigger_browser_download(
                read_zip_bytes(str(auto_path)),
                _zip_file_name(str(auto_path)),
            )
        except OSError as exc:
            st.error(f"ZIP-Download fehlgeschlagen: {exc}")
            logger.exception("Debug-Dump-Auto-Download fehlgeschlagen")

    if st.button("Debug-Dump speichern", key="chart_debug_capture_btn"):
        st.session_state[_SESSION_META_PROMPT] = True
        st.session_state.pop(_SESSION_AUTO_DOWNLOAD, None)

    if st.session_state.get(_SESSION_META_PROMPT):
        _debug_dump_meta_dialog(bundle, current_soc, live_power)
