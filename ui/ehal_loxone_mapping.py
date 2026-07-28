"""HITL Loxone structure → EHAL / loxone_blocks mapping UI (2.4.f)."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from integrations.ehal_live import reset_adapter_cache
from integrations.loxone_client import fetch_loxone_raw_value
from integrations.loxone_ehal_mapping import (
    EHAL_TO_BLOCKS,
    EXTRAS_FIELDS,
    FIELD_LABELS,
    SETPOINT_FIELDS,
    TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
    ehal_mapping_to_loxone_blocks,
    heuristic_propose,
    merge_loxone_blocks,
    ollama_reachable,
    propose_with_ollama,
)
from integrations.loxone_structure import (
    ALL_SOURCES,
    SOURCE_HTTP_PROBE,
    SOURCE_LOXAPP3,
    SOURCE_MCP17,
    SOURCE_UNION,
    StructureCompareResult,
    scan_structure,
)
from ui.house_config_io import load_main_config, save_main_config

_NONE = "— nicht gemappt —"
_SESSION_SCAN = "ehal_lox_scan"
_SESSION_COMPARE = "ehal_lox_compare"
_SESSION_PROPOSALS = "ehal_lox_proposals"
_SESSION_USE_SOURCE = "ehal_lox_use_source"

_SOURCE_LABELS = {
    SOURCE_UNION: "Union (alle Quellen)",
    SOURCE_LOXAPP3: "LoxAPP3.json",
    SOURCE_HTTP_PROBE: "Miniserver-HTTP-Probe",
    SOURCE_MCP17: "Loxone MCP 17.1",
}


def _configured_marker_names(blocks: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key, value in blocks.items():
        if key in ("log_filename", "pv_tuning_log_file"):
            continue
        text = str(value or "").strip()
        if text:
            names.append(text)
    return names


def _name_options(rows: list[dict[str, Any]], current_values: list[str]) -> list[str]:
    names = [str(row.get("name") or "") for row in rows if str(row.get("name") or "").strip()]
    for value in current_values:
        if value and value not in names:
            names.append(value)
    names.sort(key=str.lower)
    return [_NONE] + names


def _select_marker(
    field: str,
    *,
    current: str,
    options: list[str],
    required: bool,
    confidence: float | None,
) -> str:
    label = FIELD_LABELS.get(field, field)
    suffix = " *" if required else ""
    conf = ""
    if confidence is not None:
        conf = f" (Konfidenz {confidence:.0%})"
    choice = current if current in options else _NONE
    selected = st.selectbox(
        f"{label}{suffix}{conf}",
        options=options,
        index=options.index(choice) if choice in options else 0,
        key=f"ehal_lox_map_{field}",
    )
    return "" if selected == _NONE else str(selected)


def render_ehal_loxone_mapping_section() -> None:
    """Structure compare-all + HITL mapping; persists loxone_blocks after confirm."""
    st.caption(
        "One-Click-Mapping (§3.1, Research): **alle** Strukturquellen testen "
        "(LoxAPP3, HTTP-Probe, MCP 17.1), vergleichen, optional KI-Vorschlag (Ollama), "
        "dann Human-in-the-Loop → `loxone_blocks`. "
        "Noch keine feste Produktions-Quelle — Entscheidung nach Lab-Daten. "
        "Ollama ist optional und nicht Teil des Earnie-Container-Images."
    )

    data = load_main_config()
    blocks = (
        dict(data.get("loxone_blocks") or {})
        if isinstance(data.get("loxone_blocks"), dict)
        else {}
    )
    reverse_current = {
        ehal: str(blocks.get(role) or "")
        for ehal, role in EHAL_TO_BLOCKS.items()
    }
    for role in EXTRAS_FIELDS:
        reverse_current[role] = str(blocks.get(role) or "")

    mcp_url = st.text_input(
        "Loxone MCP 17.1 Base-URL (optional)",
        value=str(st.session_state.get("ehal_lox_mcp_url") or ""),
        key="ehal_lox_mcp_url",
        help="Für den MCP-Vergleichs-Lauf; leer = Variante wird als übersprungen markiert.",
    ).strip()
    ollama_url = st.text_input(
        "Ollama URL",
        value=str(st.session_state.get("ehal_lox_ollama_url") or "http://127.0.0.1:11434"),
        key="ehal_lox_ollama_url",
    ).strip() or "http://127.0.0.1:11434"
    ollama_model = st.text_input(
        "Ollama Modell",
        value=str(st.session_state.get("ehal_lox_ollama_model") or "llama3.2"),
        key="ehal_lox_ollama_model",
    ).strip() or "llama3.2"

    col_scan, col_ai = st.columns(2)
    with col_scan:
        scan_clicked = st.button("Alle Quellen testen", key="ehal_lox_scan_btn")
    with col_ai:
        ai_clicked = st.button("KI-Vorschlag (Ollama)", key="ehal_lox_ai_btn")

    if scan_clicked:
        _run_structure_scan(blocks, mcp_url)

    compare = st.session_state.get(_SESSION_COMPARE)
    if isinstance(compare, dict) and compare.get("rows"):
        st.markdown("**Quellenvergleich** (Research — noch keine Winner-Entscheidung)")
        st.dataframe(compare["rows"], use_container_width=True, hide_index=True)
        for err in (compare.get("errors") or [])[:8]:
            st.caption(err)

    use_source = _render_source_picker(compare if isinstance(compare, dict) else {})
    rows: list[dict[str, Any]] = list(st.session_state.get(_SESSION_SCAN) or [])
    if rows:
        st.caption(f"{len(rows)} Namen für Mapping ({_SOURCE_LABELS.get(use_source, use_source)})")
        st.dataframe(rows[:40], use_container_width=True, hide_index=True)
        if len(rows) > 40:
            st.caption(f"... und {len(rows) - 40} weitere.")

    if ai_clicked:
        _run_ai_propose(rows, ollama_url, ollama_model)

    proposals: dict[str, dict[str, Any]] = dict(
        st.session_state.get(_SESSION_PROPOSALS) or {}
    )
    options = _name_options(rows, [v for v in reverse_current.values() if v])

    st.markdown("**Telemetrie (EHAL)**")
    ehal_map: dict[str, str] = {}
    for field in TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL:
        prop = proposals.get(field) or {}
        default = str(prop.get("marker_name") or reverse_current.get(field) or "")
        conf = prop.get("confidence")
        mapped = _select_marker(
            field,
            current=default if default in options else reverse_current.get(field, ""),
            options=options,
            required=field in TELEMETRY_REQUIRED,
            confidence=float(conf) if conf is not None else None,
        )
        if mapped:
            ehal_map[field] = mapped

    st.markdown("**Setpoints (EHAL)**")
    for field in SETPOINT_FIELDS:
        prop = proposals.get(field) or {}
        default = str(prop.get("marker_name") or reverse_current.get(field) or "")
        conf = prop.get("confidence")
        mapped = _select_marker(
            field,
            current=default if default in options else reverse_current.get(field, ""),
            options=options,
            required=False,
            confidence=float(conf) if conf is not None else None,
        )
        if mapped:
            ehal_map[field] = mapped

    st.markdown("**Loxone-Extras** (nicht M1-EHAL)")
    extras: dict[str, str] = {}
    for field in EXTRAS_FIELDS:
        prop = proposals.get(field) or {}
        default = str(prop.get("marker_name") or reverse_current.get(field) or "")
        conf = prop.get("confidence")
        mapped = _select_marker(
            field,
            current=default if default in options else reverse_current.get(field, ""),
            options=options,
            required=False,
            confidence=float(conf) if conf is not None else None,
        )
        if mapped:
            extras[field] = mapped

    if st.button("Mapping speichern", key="ehal_lox_save_btn", type="primary"):
        _save_mapping(data, blocks, ehal_map, extras)


def _render_source_picker(compare: dict[str, Any]) -> str:
    available = [SOURCE_UNION]
    for source in ALL_SOURCES:
        if any(row.get("source") == source for row in (compare.get("rows") or [])):
            available.append(source)
    labels = [_SOURCE_LABELS.get(s, s) for s in available]
    current = str(st.session_state.get(_SESSION_USE_SOURCE) or SOURCE_UNION)
    if current not in available:
        current = SOURCE_UNION
    picked_label = st.selectbox(
        "Namen für Mapping aus",
        options=labels,
        index=labels.index(_SOURCE_LABELS.get(current, current)),
        key="ehal_lox_source_pick",
        help="Research: Union = alle gefundenen Namen; Einzelquelle zum Vergleich.",
    )
    source = next(
        (s for s in available if _SOURCE_LABELS.get(s, s) == picked_label),
        SOURCE_UNION,
    )
    if source != st.session_state.get(_SESSION_USE_SOURCE):
        st.session_state[_SESSION_USE_SOURCE] = source
        _apply_selected_source(source)
    return source


def _apply_selected_source(source: str) -> None:
    raw = st.session_state.get(_SESSION_COMPARE)
    if not isinstance(raw, dict) or "result" not in raw:
        return
    result: StructureCompareResult = raw["result"]
    result.selected_source = source
    items = result.mapping_items(use_source=source)
    st.session_state[_SESSION_SCAN] = [
        {
            "name": item.name,
            "uuid": item.uuid,
            "type": item.type,
            "room": item.room,
            "category": item.category,
            "source": item.source,
        }
        for item in items
    ]
    if items:
        st.session_state[_SESSION_PROPOSALS] = heuristic_propose(
            [item.name for item in items]
        )


def _run_structure_scan(blocks: dict[str, Any], mcp_url: str) -> None:
    st.session_state.pop(_SESSION_PROPOSALS, None)
    host = str(config.get("LOXONE_IP") or "")
    user = str(config.get("LOXONE_USER") or "")
    password = str(config.get("LOXONE_PASS") or "")
    result = scan_structure(
        host=host,
        username=user,
        password=password,
        configured_names=_configured_marker_names(blocks),
        mcp_base_url=mcp_url,
        fetch_raw=fetch_loxone_raw_value,
        selected_source=SOURCE_UNION,
    )
    st.session_state[_SESSION_USE_SOURCE] = SOURCE_UNION
    st.session_state[_SESSION_COMPARE] = {
        "rows": result.comparison_rows(),
        "errors": result.all_errors(),
        "result": result,
    }
    items = result.mapping_items(use_source=SOURCE_UNION)
    st.session_state[_SESSION_SCAN] = [
        {
            "name": item.name,
            "uuid": item.uuid,
            "type": item.type,
            "room": item.room,
            "category": item.category,
            "source": item.source,
        }
        for item in items
    ]
    if items:
        st.session_state[_SESSION_PROPOSALS] = heuristic_propose(
            [item.name for item in items]
        )


def _run_ai_propose(
    rows: list[dict[str, Any]],
    ollama_url: str,
    ollama_model: str,
) -> None:
    names = [str(row.get("name") or "") for row in rows if row.get("name")]
    if not names:
        st.error("Zuerst alle Quellen testen (Namensliste leer).")
        return
    if not ollama_reachable(ollama_url):
        st.warning(
            "Ollama nicht erreichbar — Heuristik-Vorschläge bleiben aktiv. "
            "Ollama separat installieren (nicht im Earnie-Image)."
        )
        st.session_state[_SESSION_PROPOSALS] = heuristic_propose(names)
        return
    with st.spinner("Ollama mappt Merker → EHAL …"):
        proposals = propose_with_ollama(
            names, base_url=ollama_url, model=ollama_model
        )
    if not proposals:
        st.warning("Ollama lieferte keine Vorschläge — Heuristik wird genutzt.")
        proposals = heuristic_propose(names)
    else:
        st.success(f"{len(proposals)} KI-Vorschläge übernommen.")
    st.session_state[_SESSION_PROPOSALS] = proposals


def _save_mapping(
    data: dict[str, Any],
    blocks: dict[str, Any],
    ehal_map: dict[str, str],
    extras: dict[str, str],
) -> None:
    missing = [name for name in TELEMETRY_REQUIRED if name not in ehal_map]
    if missing:
        st.error("Pflichtfelder fehlen: " + ", ".join(missing))
        return
    updates = ehal_mapping_to_loxone_blocks(ehal_map, extras=extras)
    payload = dict(data)
    payload["loxone_blocks"] = merge_loxone_blocks(blocks, updates)
    ehal = dict(payload.get("ehal") or {}) if isinstance(payload.get("ehal"), dict) else {}
    if not ehal.get("backend"):
        ehal["backend"] = "loxone"
    if not ehal.get("adapter_id"):
        ehal["adapter_id"] = "loxone-home"
    payload["ehal"] = ehal
    save_main_config(payload)
    reset_adapter_cache()
    st.success("Loxone-Mapping in `loxone_blocks` gespeichert.")
    st.rerun()
