"""EHAL-Com Signal list (2.7.q Q7 / Binding P5b) — contract UI for all backends."""
from __future__ import annotations

from typing import Any

import streamlit as st

from ehal.signal_catalog import set_binding_activation
from ehal.signal_export import build_export_zip
from ehal.signal_list import SignalRow, build_signal_rows
from runtime_store.ehal_setup import BACKEND_LOXONE, active_ehal_backend
from ui.ehal_unit_display import units_for_field

_MATCH_SYMBOL = {
    "ok": "✅",
    "stale": "⚠️",
    "never": "⬜",
    "published": "✅",
    "awaiting_fetch": "⏳",
    "inactive": "·",
}
_DASH = "—"


def render_ehal_signal_list_section() -> None:
    """Contract table: qualified ID · meaning · Pflicht/aktiviert · match · export."""
    house, components = _load_docs()
    inbox = _load_inbox()
    published, fetched_at = _load_publish_state()
    backend = active_ehal_backend()
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
        "Schreiben = zuletzt vom Hub abgerufen (status.json-Callback)."
    )
    if not rows:
        st.info("Keine konfigurierten Komponenten — Hauskonfigurator prüfen.")
        return
    st.dataframe(
        _table_records(rows, backend=backend),
        use_container_width=True,
        hide_index=True,
    )
    _render_optional_toggles(house, components, rows)
    _render_export(house, components, backend=backend)


def _table_records(
    rows: list[SignalRow], *, backend: str | None = None
) -> list[dict[str, str]]:
    resolved = backend if backend is not None else active_ehal_backend()
    show_hub = resolved == BACKEND_LOXONE
    out: list[dict[str, str]] = []
    for row in rows:
        symbol = _MATCH_SYMBOL.get(row.match_kind, "·")
        req = ", ".join(row.required_by) if row.required_by else _DASH
        units = units_for_field(
            row.ehal_id, "loxone" if show_hub else "ha"
        )
        rec: dict[str, str] = {
            "Richtung": "Lesen" if row.direction == "read" else "Schreiben",
            "EHAL-ID": row.ehal_id,
            "Bedeutung": f"{row.entity_label} — {row.meaning}",
            "Pflicht": "Pflicht" if row.is_required else "optional",
            "aktiviert": "ja" if row.is_activated else "nein",
        }
        if show_hub:
            rec["Hub-Einheit"] = units.hub_unit or _DASH
        rec["EHAL-Einheit"] = units.ehal_unit or _DASH
        rec["Benötigt von"] = req
        rec["Match"] = f"{symbol} {row.match_text}"
        rec["Gruppe"] = row.group
        out.append(rec)
    return out


def _render_optional_toggles(
    house: dict, components: dict, rows: list[SignalRow]
) -> None:
    optional = [
        r
        for r in rows
        if r.binding_key and not r.is_required and r.component_kind
    ]
    if not optional:
        return
    with st.expander("Optionale Signale aktivieren / deaktivieren", expanded=False):
        st.caption(
            "Ein = Binding-Schlüssel mit leerem Wert anlegen; "
            "Aus = Schlüssel entfernen. Pflichtsignale sind nicht abschaltbar."
        )
        changed = False
        house_cur, comp_cur = house, components
        for row in optional:
            label = f"{row.ehal_id} — {row.meaning}"
            key = f"ehal_sig_opt::{row.binding_key}"
            new_val = st.checkbox(
                label,
                value=row.is_activated,
                key=key,
            )
            if bool(new_val) == bool(row.is_activated):
                continue
            try:
                house_cur, comp_cur = set_binding_activation(
                    house_cur,
                    comp_cur,
                    component_kind=row.component_kind,  # type: ignore[arg-type]
                    entity_id=row.entity_id,
                    binding_key=row.binding_key,
                    activated=bool(new_val),
                    consumer_type=row.consumer_type,
                    is_required=False,
                )
                changed = True
            except ValueError as exc:
                st.error(str(exc))
        if changed:
            _persist_docs(house_cur, comp_cur)
            st.rerun()


def _persist_docs(house: dict, components: dict) -> None:
    from ui.house_config_io import (
        _save_components_document,
        save_house_profiles,
    )

    save_house_profiles(house)
    _save_components_document(components)


def _render_export(house: dict, components: dict, *, backend: str) -> None:
    st.subheader("Export")
    mode = st.radio(
        "Umfang",
        options=["needed", "all"],
        format_func=lambda m: (
            "nur aktivierte"
            if m == "needed"
            else "alle (Pflicht + optional)"
        ),
        horizontal=True,
        key="ehal_signal_export_mode",
    )
    if backend == BACKEND_LOXONE:
        st.caption("Loxone: ZIP mit VO-/VI-Vorlagen und Signallisten-CSV.")
    else:
        st.caption(
            "Loxone-VO/VI-Export (ZIP). HA-YAML-Paket folgt mit Binding P5c."
        )
    host = st.text_input(
        "Earnie-Host (LAN-IP für den Hub)",
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
        file_name="earnie_signal_export.zip",
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
        if cfg is not None and hasattr(cfg, "get_ehal_http_port"):
            return int(cfg.get_ehal_http_port())
        raw = getattr(cfg, "ehal_http_port", None) if cfg else None
        if raw is None and cfg is not None:
            raw = getattr(cfg, "ehal_loxone_http_port", None)
        if raw is None and cfg is not None:
            system = getattr(cfg, "system", None) or {}
            if isinstance(system, dict):
                raw = system.get("ehal_http_port", system.get("ehal_loxone_http_port"))
        return int(raw or 8541)
    except Exception:  # noqa: BLE001
        return 8541
