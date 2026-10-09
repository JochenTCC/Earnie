"""EHAL-Com Signal list (2.7.q Q7) — replaces Loxone Struktur → EHAL Mapping."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ehal.signal_export import build_export_zip
from ehal.signal_list import SignalRow, build_signal_rows

_MATCH_SYMBOL = {
    "ok": "✅",
    "stale": "⚠️",
    "never": "⬜",
    "published": "✅",
    "awaiting_fetch": "⏳",
}


def render_ehal_signal_list_section() -> None:
    """Contract table: qualified ID · meaning · required by · match · export."""
    house, components = _load_docs()
    inbox = _load_inbox()
    published, fetched_at = _load_publish_state()
    rows = build_signal_rows(
        house,
        components,
        inbox=inbox,
        published=published,
        fetched_at=fetched_at,
    )
    st.caption(
        "Earnie definiert die Signale (qualifizierte EHAL-IDs). "
        "Match-Status: Lesen = zuletzt empfangen (Push-Inbox); "
        "Schreiben = zuletzt vom Miniserver abgerufen (status.json-Callback)."
    )
    if not rows:
        st.info("Keine aktivierten Bindings — Import oder Hauskonfigurator prüfen.")
        return
    st.dataframe(_table_records(rows), use_container_width=True, hide_index=True)
    _render_export(house, components)


def _table_records(rows: list[SignalRow]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        symbol = _MATCH_SYMBOL.get(row.match_kind, "·")
        req = ", ".join(row.required_by) if row.required_by else "—"
        out.append(
            {
                "Richtung": "Lesen" if row.direction == "read" else "Schreiben",
                "EHAL-ID": row.ehal_id,
                "Bedeutung": f"{row.entity_label} — {row.meaning}",
                "Benötigt von": req,
                "Match": f"{symbol} {row.match_text}",
                "Gruppe": row.group,
            }
        )
    return out


def _render_export(house: dict, components: dict) -> None:
    st.subheader("Export VO / VI")
    mode = st.radio(
        "Umfang",
        options=["needed", "all"],
        format_func=lambda m: "nur benötigte (aktivierte Bindings)" if m == "needed" else "alle (wie benötigt)",
        horizontal=True,
        key="ehal_signal_export_mode",
    )
    host = st.text_input(
        "Earnie-Host (LAN-IP für Loxone)",
        value=_default_host(),
        key="ehal_signal_export_host",
    )
    port = st.number_input(
        "HTTP-Port",
        min_value=1,
        max_value=65535,
        value=_default_port(),
        key="ehal_signal_export_port",
    )
    if not str(host or "").strip():
        st.caption("Host eingeben, um den ZIP-Download freizuschalten.")
        return
    try:
        payload = build_export_zip(
            house,
            components,
            host=str(host).strip(),
            port=int(port),
            mode=mode,  # type: ignore[arg-type]
        )
    except Exception as exc:  # noqa: BLE001 — show in UI
        st.error(f"Export fehlgeschlagen: {exc}")
        return
    st.download_button(
        "ZIP herunterladen (VO + VI + README)",
        data=payload,
        file_name="earnie_loxone_signal_export.zip",
        mime="application/zip",
        key="ehal_signal_export_zip",
    )


def _load_docs() -> tuple[dict, dict]:
    from ui.house_config_io import _load_components_document, load_house_profiles

    house = load_house_profiles()
    try:
        components = _load_components_document()
    except Exception:  # noqa: BLE001
        components = {"batteries": [], "pv_systems": []}
    if not isinstance(components, dict):
        components = {"batteries": [], "pv_systems": []}
    return house if isinstance(house, dict) else {}, components


def _load_inbox() -> dict[str, dict[str, Any]]:
    try:
        from runtime_store.loxone_push_inbox import load_inbox

        return load_inbox()
    except Exception:  # noqa: BLE001
        return {}


def _load_publish_state() -> tuple[dict[str, dict[str, Any]], str | None]:
    try:
        from integrations.ehal_write import load_published_records, published_fetched_at

        return load_published_records(), published_fetched_at()
    except Exception:  # noqa: BLE001
        return {}, None


def _default_host() -> str:
    import os

    return str(os.environ.get("EARNIE_LAN_IP") or os.environ.get("EARNIE_HOST") or "").strip()


def _default_port() -> int:
    try:
        import config

        cfg = getattr(config, "CONFIG", None)
        raw = getattr(cfg, "ehal_loxone_http_port", None) if cfg else None
        if raw is None and cfg is not None:
            system = getattr(cfg, "system", None) or {}
            if isinstance(system, dict):
                raw = system.get("ehal_loxone_http_port")
        return int(raw or 8541)
    except Exception:  # noqa: BLE001
        return 8541
