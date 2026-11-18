"""Sidebar "Sichern & Übertragen" → Support-Paket (light config ZIP or full debug dump)."""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime
from typing import Any

import streamlit as st

import config
from integrations.live_power_capture import capture_live_power
from runtime_store.chart_debug_capture import build_chart_section, read_zip_bytes
from runtime_store.debug_dump_archive import write_debug_dump_zip
from ui.charts import build_power_soc_chart_figure
from ui.history_navigation import get_s2_cycle_offset, get_s2_segment_index, get_s2_span
from ui.simulation_results import SESSION_LIVE_DISPLAY_BUNDLE

logger = logging.getLogger("app")

CONFIG_ONLY_ZIP_PREFIX = "earnie_konfiguration_support"
CONFIG_PACK_ARCNAME = "earnie_config_pack.zip"
ATTACHMENTS_ARCDIR = "anhänge"

_SESSION_LIVE_SOC = "support_package_live_soc"
_SESSION_LAST_PATH = "support_package_last_path"
_SESSION_ERROR = "support_package_error"


def remember_live_soc(current_soc: float | None) -> None:
    """Monitor page: keep the SoC shown with the chart for the next support package."""
    st.session_state[_SESSION_LIVE_SOC] = current_soc


def build_config_only_bundle_bytes(
    attachments: list[Any] | None,
    *,
    config_pack: bytes,
) -> bytes:
    """ZIP with the config pack plus optional uploaded attachments (no history, no logs)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(CONFIG_PACK_ARCNAME, config_pack)
        for name, data in _attachment_pairs(attachments):
            archive.writestr(f"{ATTACHMENTS_ARCDIR}/{name}", data)
    return buffer.getvalue()


def _attachment_pairs(attachments: list[Any] | None) -> list[tuple[str, bytes]]:
    pairs: list[tuple[str, bytes]] = []
    for uploaded in attachments or []:
        name = getattr(uploaded, "name", None) or "anhang.bin"
        data = uploaded.getvalue() if hasattr(uploaded, "getvalue") else bytes(uploaded)
        pairs.append((name, data))
    return pairs


def _timestamped_name(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"


def _session_meta() -> dict[str, Any]:
    return {
        "live_optimization_cache_key": st.session_state.get("live_optimization_cache_key"),
        "s2_cycle_offset": get_s2_cycle_offset(),
        "s2_segment_index": get_s2_segment_index(),
        "s2_span": get_s2_span(),
    }


def _chart1_plotly_json(bundle) -> str | None:
    try:
        chart_now = None
        if bundle.chart_context is not None:
            chart_now = bundle.chart_context.zone_reference
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
            chart_now=chart_now,
            battery_params=getattr(bundle, "battery_params", None),
        )
        return fig.to_json()
    except Exception as exc:
        logger.warning("Support-Paket: Plotly Chart 1 konnte nicht serialisiert werden: %s", exc)
        return None


def save_full_support_package(
    *,
    title: str,
    symptom: str,
    attachments: list[tuple[str, bytes]],
) -> str:
    """Write the full support package (debug dump schema v3); returns the ZIP path."""
    bundle = st.session_state.get(SESSION_LIVE_DISPLAY_BUNDLE)
    chart_payload = None
    if bundle is not None:
        # Same read as the Live Sankey, taken at capture time (+ push state per signal).
        live = capture_live_power()
        chart_payload = build_chart_section(
            bundle,
            current_soc=st.session_state.get(_SESSION_LIVE_SOC),
            live_power=live["live_power"],
            live_power_capture=live["live_power_capture"],
            session_meta=_session_meta(),
            chart1_plotly_json=_chart1_plotly_json(bundle),
        )
    return write_debug_dump_zip(
        chart_payload=chart_payload,
        title=title.strip(),
        symptom=symptom.strip(),
        attachments=attachments,
    )


def _zip_file_name(zip_path: str) -> str:
    return zip_path.split("/")[-1].split("\\")[-1]


def _render_config_only_download(attachments: list[Any], config_pack: bytes) -> None:
    st.markdown("**Nur Konfiguration**")
    st.caption(
        "Konfigurations-ZIP plus Anhänge, ohne Historie und Logs. Hilft nur bei "
        "Fragen, die **nicht** den Live-Betrieb betreffen (Einrichtung, Hausprofil, "
        "Szenarien, Backtesting)."
    )
    try:
        payload = build_config_only_bundle_bytes(attachments, config_pack=config_pack)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        st.error(f"ZIP-Erstellung fehlgeschlagen: {exc}")
        logger.exception("Support-Paket (nur Konfiguration) fehlgeschlagen")
        return
    st.download_button(
        label="Konfiguration + Anhänge herunterladen",
        data=payload,
        file_name=_timestamped_name(CONFIG_ONLY_ZIP_PREFIX),
        mime="application/zip",
        key="support_package_config_only_download",
        width="stretch",
    )


def _render_full_package(attachments: list[Any]) -> None:
    st.markdown("**Vollständig (Live-Betrieb)**")
    st.caption(
        "Zusätzlich gesamte Optimierer-Historie, Cycle-Recorder "
        f"(bis zu {config.get_recorder_retention_days()} Tage Lastprofile), "
        "Logs und — wenn die Monitor-Seite in dieser Sitzung offen war — die "
        "Chart-Daten. Nur an den Maintainer weitergeben, nicht öffentlich teilen."
    )
    st.text_input("Titel (optional)", key="support_package_title")
    st.text_area("Symptom (optional)", key="support_package_symptom")
    if st.button(
        "Support-Paket erstellen",
        key="support_package_create_btn",
        width="stretch",
    ):
        try:
            with st.spinner("ZIP wird erstellt …"):
                path = save_full_support_package(
                    title=str(st.session_state.get("support_package_title") or ""),
                    symptom=str(st.session_state.get("support_package_symptom") or ""),
                    attachments=_attachment_pairs(attachments),
                )
        except (OSError, ValueError) as exc:
            logger.exception("Support-Paket konnte nicht erstellt werden")
            st.session_state.pop(_SESSION_LAST_PATH, None)
            st.session_state[_SESSION_ERROR] = str(exc)
        else:
            st.session_state[_SESSION_LAST_PATH] = path
            st.session_state.pop(_SESSION_ERROR, None)

    error = st.session_state.get(_SESSION_ERROR)
    if error:
        st.error(f"Support-Paket konnte nicht erstellt werden: {error}")
    last_path = st.session_state.get(_SESSION_LAST_PATH)
    if not last_path:
        return
    try:
        data = read_zip_bytes(str(last_path))
    except OSError as exc:
        st.error(f"Support-Paket nicht lesbar: {exc}")
        st.session_state.pop(_SESSION_LAST_PATH, None)
        return
    st.success(f"Gespeichert: `{_zip_file_name(str(last_path))}`")
    st.download_button(
        label="Support-Paket herunterladen",
        data=data,
        file_name=_zip_file_name(str(last_path)),
        mime="application/zip",
        type="primary",
        key="support_package_download",
        width="stretch",
    )


def render_support_package_controls(config_pack: bytes | None) -> None:
    """Attachments + both variants; ``config_pack`` is None when its export failed."""
    st.markdown("#### Support-Paket")
    st.caption(
        "Für Anfragen an den Support. Das ZIP bleibt lokal: an ein öffentliches "
        "GitHub-Issue nur sichere Ausschnitte, Vertrauliches per E-Mail "
        "(siehe **Info / About → Kontakt**)."
    )
    attachments = st.file_uploader(
        "Anhänge (optional, z. B. Screenshots)",
        accept_multiple_files=True,
        key="support_package_attachments",
    )
    attachment_list = list(attachments or [])
    if config_pack is not None:
        _render_config_only_download(attachment_list, config_pack)
    _render_full_package(attachment_list)
