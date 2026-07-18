"""Sidebar UI for Earnie config pack export/import."""
from __future__ import annotations

import logging

import streamlit as st

from runtime_store.config_pack import (
    build_config_pack_bytes,
    default_pack_filename,
    import_config_pack_bytes,
)
from runtime_store.data_model import DataModelError

logger = logging.getLogger(__name__)

_EDITOR_SESSION_PREFIXES = (
    "house_profile_",
    "scenario_editor_",
    "planning_pv_",
    "planning_battery_",
    "_auto_persist_fp::",
)


def _clear_session_after_config_import() -> None:
    """Drop editor/live UI state so imported JSON is not masked by stale widgets."""
    from ui.chart_consumer_stack import clear_consumer_stack_order_cache
    from ui.simulation_results import SESSION_LIVE_DISPLAY_BUNDLE

    clear_consumer_stack_order_cache()
    st.session_state.pop(SESSION_LIVE_DISPLAY_BUNDLE, None)
    for key in list(st.session_state.keys()):
        if not isinstance(key, str):
            continue
        if any(key.startswith(prefix) for prefix in _EDITOR_SESSION_PREFIXES):
            del st.session_state[key]


def render_config_pack_sidebar() -> None:
    with st.sidebar.expander("Konfiguration speichern / laden", expanded=False):
        st.caption(
            "Exportiert bzw. importiert die JSON-Konfiguration und CSV-Uploads "
            "als ZIP (ohne .env / Zugangsdaten)."
        )
        try:
            payload = build_config_pack_bytes()
        except Exception as exc:  # noqa: BLE001 — surface to user
            st.error(f"Export fehlgeschlagen: {exc}")
            logger.exception("config pack export failed")
            payload = b""
        if payload:
            st.download_button(
                label="ZIP herunterladen",
                data=payload,
                file_name=default_pack_filename(),
                mime="application/zip",
                key="config_pack_download",
            )
        uploaded = st.file_uploader(
            "ZIP importieren",
            type=["zip"],
            key="config_pack_upload",
        )
        if uploaded is not None and st.button(
            "Importieren und neu laden",
            key="config_pack_import_btn",
        ):
            try:
                written = import_config_pack_bytes(uploaded.getvalue())
            except (DataModelError, ValueError, OSError, KeyError) as exc:
                st.error(str(exc))
                logger.warning("config pack import rejected: %s", exc)
            else:
                st.success(f"Importiert: {len(written)} Datei(en).")
                _clear_session_after_config_import()
                st.cache_data.clear()
                st.rerun()
