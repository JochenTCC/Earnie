"""Sidebar "Sichern & Übertragen": config pack export/import + support package."""
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


def _render_config_pack_export(payload: bytes | None) -> None:
    if payload is None:
        return
    st.download_button(
        label="Konfiguration herunterladen",
        data=payload,
        file_name=default_pack_filename(),
        mime="application/zip",
        key="config_pack_download",
        width="stretch",
    )


def _render_config_pack_import() -> None:
    uploaded = st.file_uploader(
        "Konfiguration importieren (ZIP)",
        type=["zip"],
        key="config_pack_upload",
    )
    if uploaded is None or not st.button(
        "Importieren und neu laden",
        key="config_pack_import_btn",
    ):
        return
    try:
        written = import_config_pack_bytes(uploaded.getvalue())
    except (DataModelError, ValueError, OSError, KeyError) as exc:
        st.error(str(exc))
        logger.warning("config pack import rejected: %s", exc)
        return
    st.success(f"Importiert: {len(written)} Datei(en).")
    _clear_session_after_config_import()
    st.cache_data.clear()
    st.rerun()


def build_config_pack_for_sidebar() -> bytes | None:
    """Config pack bytes for this run, or None (error shown) when the export fails."""
    try:
        return build_config_pack_bytes()
    except Exception as exc:  # noqa: BLE001 — surface to user
        st.error(f"Konfigurations-Export fehlgeschlagen: {exc}")
        logger.exception("config pack export failed")
        return None


def render_config_pack_controls(payload: bytes | None) -> None:
    st.markdown("#### Konfiguration sichern / laden")
    st.caption(
        "JSON-Konfiguration und CSV-Uploads als ZIP (ohne .env / Zugangsdaten) — "
        "als Backup oder zum Umzug auf ein anderes Gerät."
    )
    _render_config_pack_export(payload)
    _render_config_pack_import()


def render_backup_transfer_sidebar() -> None:
    """Sidebar "Sichern & Übertragen": everything that moves data in or out of Earnie."""
    from ui.support_package import render_support_package_controls

    with st.sidebar.expander("Sichern & Übertragen", expanded=False):
        payload = build_config_pack_for_sidebar()
        render_config_pack_controls(payload)
        st.divider()
        render_support_package_controls(payload)
