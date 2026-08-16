"""EHAL Loxone mapping Streamlit section UI."""
from __future__ import annotations

import config
from ui.ehal_loxone_mapping import (
    _clear_pending_for_widget,
    _ensure_ehal_loxone_meta,
    _field_select_caption,
    _migrate_on_open,
    _name_options,
    _queue_pending_new_marker,
    _render_field_selects,
    _save_entity_mapping,
    add_manual_marker_name,
    apply_entity_bindings,
    build_entity_rows,
    configured_marker_names,
    is_known_marker_name,
    resolve_live_profile_id,
    session_manual_marker_names,
)

from typing import Any

import streamlit as st

import config
from ehal.profiles import group_fields_by_role, role_field_labels, role_group_label
from house_config.ehal_bindings import (
    FILTER_EHAL_FIELDS,
    THERMAL_RC_EHAL_FIELDS,
    ensure_migrated,
    filter_ehal_fields_for_consumer,
    strip_migrated_config_keys,
)
from integrations.ehal_live import reset_adapter_cache
from integrations.loxone_ehal_mapping import (
    FIELD_LABELS,
    SETPOINT_FIELDS,
    TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
    heuristic_propose,
)
from integrations.loxone_greenfield_import import probe_marker_names
from integrations.loxone_structure import (
    SOURCE_HTTP_PROBE,
    scan_structure,
)
from ui.house_config_io import (
    get_live_scenario_refs,
    load_house_profiles,
    load_main_config,
    save_house_profiles,
    save_main_config,
)

_NONE = "— nicht gemappt —"
_SESSION_SCAN = "ehal_lox_scan"
_SESSION_PROPOSALS = "ehal_lox_proposals"
_SESSION_ENTITY = "ehal_lox_entity_id"
_SESSION_MIGRATED = "ehal_lox_migrated_once"
_SESSION_MANUAL_NAMES = "ehal_lox_manual_names"
_SESSION_MANUAL_FEEDBACK = "ehal_lox_manual_feedback"
_SESSION_PENDING_NEW = "ehal_lox_pending_new_marker"

PLANT_ENTITY_ID = "plant"

PLANT_FIELDS: tuple[str, ...] = (
    TELEMETRY_REQUIRED
    + tuple(f for f in TELEMETRY_OPTIONAL if f != "sens_evcs_active_power")
    + tuple(
        f
        for f in SETPOINT_FIELDS
        if f.startswith("set_ess_")
    )
)

EV_FIELDS: tuple[str, ...] = (
    "sens_evcs_active_power",
    "sens_evcs_connected",
    "sens_evcs_soc_act",
    "get_evcs_nominal_current",
    "sens_evcs_bat_capacity",
    "get_evcs_ready_by_time",
    "get_evcs_limit_soc",
    "get_evcs_soc_min_immediate",
    "set_evcs_max_current",
    "set_evcs_mode",
)

FLEX_FIELDS: tuple[str, ...] = (
    "flex.sens_power_act",
    "flex.set_enable",
    "flex.set_power_setpoint",
)

FILTER_FIELDS: tuple[str, ...] = FILTER_EHAL_FIELDS

_EXTRA_LABELS: dict[str, str] = {
    "sens_evcs_connected": "EV angeschlossen",
    "sens_evcs_soc_act": "EV Ist-SOC (%)",
    "get_evcs_nominal_current": "EV Nennstrom (A)",
    "sens_evcs_bat_capacity": "EV Batteriekapazität (kWh)",
    "get_evcs_ready_by_time": "EV FertigUm",
    "get_evcs_limit_soc": "EV Ladeziel-SOC (%)",
    "get_evcs_soc_min_immediate": "EV SOC-Min Sofort (%)",
    "flex.power_name": "Flex Leistung / Zustand",
    "flex.enable_name": "Flex Freigabe",
    "flex.power_setpoint_name": "Flex Leistungs-Sollwert",
    "flex.sens_power_act": "Flex Leistung / Zustand",
    "flex.set_enable": "Flex Freigabe",
    "flex.set_power_setpoint": "Flex Leistungs-Sollwert",
    "get_filter_remaining_hours": "Filter Sollstunden (h)",
    "sens_filter_active": "Filter läuft (Binär)",
    "get_filter_native_start_hour": "Native Filter-Startstunde",
    "get_filter_native_duration_hours": "Native Filter-Dauer (h)",
    "sens_temperature_water": "Pool Ist-Temperatur (°C)",
    "get_temperature_water_setpoint": "Pool Soll-Temperatur (°C)",
    "get_temperature_tolerance_c": "Temperatur-Toleranz (°C)",
    "sens_heating_active": "Heizung aktiv",
    "sens_temperature_outside": "Außentemperatur (°C)",
}



def _select_marker(
    field: str,
    *,
    entity_id: str,
    profile_id: str,
    current: str,
    options: list[str],
    required: bool,
    key: str,
) -> str:
    choice = current if current in options else _NONE
    if key not in st.session_state and current and current not in options and current != _NONE:
        # Restore a typed/custom value that is not yet in the shared options list.
        st.session_state[key] = current
    selected = st.selectbox(
        _field_select_caption(field, required=required),
        options=options,
        index=options.index(choice) if choice in options else 0,
        key=key,
        accept_new_options=True,
        help="Bekannten Merker wählen oder neuen Namen eintippen (Bestätigung folgt).",
    )
    if selected is None or selected == _NONE or not str(selected).strip():
        _clear_pending_for_widget(key)
        return ""
    text = str(selected).strip()
    known_pool = options + session_manual_marker_names()
    if is_known_marker_name(text, known_pool):
        _clear_pending_for_widget(key)
        return text
    _queue_pending_new_marker(
        entity_id=entity_id,
        profile_id=profile_id,
        field=field,
        name=text,
        widget_key=key,
    )
    return ""

def render_ehal_loxone_mapping_section() -> None:
    """HTTP-probe structure scan + entity HITL; persists plant/consumer ehal_bindings."""
    st.caption(
        "Entity-zentriertes Mapping: Anlage + Verbraucher aus dem Live-Hausprofil. "
        "Pool/SwimSpa-Filter: Verbraucher `pool_filter` mit `ehal_bindings` "
        "(`get_filter_remaining_hours`, Freigabe, natives Fenster u. a.). "
        "Felder `{entity}.{ehal_field}` → Merker; Speichern in `house_profiles.json` "
        "(`plant` / `consumers[].ehal_bindings`). "
        "Außerplanmäßige Optimierung: Loxone VO `Earnie_Request_Optimize` "
        "(Daemon-HTTP, Port `system.ehal_loxone_http_port`, Standard 8541). "
        "Struktur-Scan: HTTP-Probe bekannter Earnie_*/gemappter Merker; "
        "in jedem Feld-Dropdown einen neuen Merker eintippen (mit Bestätigung)."
    )
    house, config_doc = _migrate_on_open()
    profile_id = resolve_live_profile_id(house)
    entities = build_entity_rows(house, profile_id)
    if not profile_id:
        st.warning("Kein Hausprofil im Live-Szenario — bitte zuerst im Szenarienkonfigurator setzen.")
        return
    feedback = st.session_state.pop(_SESSION_MANUAL_FEEDBACK, None)
    if feedback:
        st.info(feedback)
    rows = _render_http_probe_scan(house, profile_id)
    entity = _render_entity_picker(entities)
    proposals: dict[str, dict[str, Any]] = dict(st.session_state.get(_SESSION_PROPOSALS) or {})
    options = _name_options(
        rows,
        list(entity["bindings"].values()),
        session_manual_marker_names(),
    )
    ehal_map = _render_field_selects(
        entity,
        options,
        proposals,
        profile_id=profile_id,
    )
    pending = st.session_state.get(_SESSION_PENDING_NEW)
    if isinstance(pending, dict) and str(pending.get("name") or "").strip():
        _confirm_new_marker_dialog(house, config_doc)
    if st.button("Mapping speichern", key="ehal_lox_save_btn", type="primary"):
        _save_entity_mapping(
            house,
            config_doc,
            profile_id=profile_id,
            entity_id=str(entity["id"]),
            ehal_map=ehal_map,
        )

def _render_http_probe_scan(house: dict, profile_id: str) -> list[dict[str, Any]]:
    """Scan via HTTP-Probe only (MCP / Ollama / Quellenvergleich UI removed; code kept in integrations)."""
    if st.button("HTTP-Probe", key="ehal_lox_scan_btn"):
        configured = configured_marker_names(house, profile_id) + session_manual_marker_names()
        _run_structure_scan(configured)
    rows: list[dict[str, Any]] = list(st.session_state.get(_SESSION_SCAN) or [])
    if rows:
        st.caption(f"{len(rows)} Namen für Mapping (HTTP-Probe)")
        st.dataframe(rows[:40], width="stretch", hide_index=True)
        if len(rows) > 40:
            st.caption(f"... und {len(rows) - 40} weitere.")
        errors = st.session_state.get("ehal_lox_scan_errors") or []
        for err in errors[:8]:
            st.caption(err)
    return rows

def _manual_add_probe_caption(name: str) -> str:
    """Non-blocking HTTP presence check after manual add; always keeps the name in the list."""
    host = str(config.get("LOXONE_IP") or "")
    username = str(config.get("LOXONE_USER") or "")
    password = str(config.get("LOXONE_PASS") or "")
    if not host.strip() or not username.strip():
        return (
            f"`{name}` gespeichert und zugeordnet "
            "(keine Loxone-Zugangsdaten — HTTP-Probe übersprungen)."
        )
    try:
        result = probe_marker_names(
            [name],
            host=host,
            username=username,
            password=password,
            timeout_sec=5.0,
        )
    except ValueError as exc:
        return f"`{name}` gespeichert und zugeordnet (Probe fehlgeschlagen: {exc})."
    if name in result.present:
        return f"`{name}` gespeichert und zugeordnet — HTTP-Probe: auf dem Miniserver vorhanden."
    if name in result.missing:
        return (
            f"`{name}` gespeichert und zugeordnet — HTTP-Probe: 404 (fehlt noch); "
            "Mapping trotzdem aktiv."
        )
    return f"`{name}` gespeichert und zugeordnet (Probe ohne eindeutigen Status)."

@st.dialog("Neuer Merker?")
def _confirm_new_marker_dialog(house: dict, config_doc: dict) -> None:
    pending = st.session_state.get(_SESSION_PENDING_NEW) or {}
    name = str(pending.get("name") or "").strip()
    field = str(pending.get("field") or "").strip()
    entity_id = str(pending.get("entity_id") or "").strip()
    st.markdown(
        f"Unbekannter Merker `{name}` für EHAL-Feld `{field}` "
        f"(Entity `{entity_id}`)."
    )
    st.caption("Als neuen Merker speichern und diesem Feld zuordnen?")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Ja, speichern und zuordnen", type="primary", key="ehal_lox_new_yes"):
            _accept_pending_new_marker(house, config_doc)
            st.rerun()
    with col_no:
        if st.button("Nein", key="ehal_lox_new_no"):
            widget_key = str(pending.get("widget_key") or "")
            if widget_key:
                st.session_state[widget_key] = _NONE
            st.session_state.pop(_SESSION_PENDING_NEW, None)
            st.rerun()

def _accept_pending_new_marker(house: dict, config_doc: dict) -> None:
    pending = st.session_state.get(_SESSION_PENDING_NEW) or {}
    name = str(pending.get("name") or "").strip()
    field = str(pending.get("field") or "").strip()
    entity_id = str(pending.get("entity_id") or "").strip()
    profile_id = str(pending.get("profile_id") or "").strip()
    widget_key = str(pending.get("widget_key") or "")
    if not (name and field and entity_id and profile_id):
        st.session_state.pop(_SESSION_PENDING_NEW, None)
        return
    existing = list(st.session_state.get(_SESSION_MANUAL_NAMES) or [])
    updated, _hint = add_manual_marker_name(existing, name)
    st.session_state[_SESSION_MANUAL_NAMES] = updated
    rows = build_entity_rows(house, profile_id)
    entity = next((row for row in rows if row["id"] == entity_id), None)
    bindings = dict(entity["bindings"]) if entity else {}
    bindings[field] = name
    migrated_house, migrated_config, _ = ensure_migrated(house, config_doc)
    saved = apply_entity_bindings(
        migrated_house,
        profile_id=profile_id,
        entity_id=entity_id,
        bindings=bindings,
    )
    save_house_profiles(saved)
    save_main_config(_ensure_ehal_loxone_meta(migrated_config))
    reset_adapter_cache()
    if widget_key:
        st.session_state[widget_key] = name
    st.session_state.pop(_SESSION_PENDING_NEW, None)
    st.session_state[_SESSION_MANUAL_FEEDBACK] = _manual_add_probe_caption(name)

def _render_entity_picker(entities: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [f"{row['label']} (`{row['id']}`)" for row in entities]
    ids = [str(row["id"]) for row in entities]
    current = str(st.session_state.get(_SESSION_ENTITY) or PLANT_ENTITY_ID)
    if current not in ids:
        current = ids[0] if ids else PLANT_ENTITY_ID
    st.markdown("#### Entity")
    picked = st.selectbox(
        "Entity",
        options=labels,
        index=ids.index(current) if current in ids else 0,
        key="ehal_lox_entity_pick",
        label_visibility="collapsed",
    )
    entity_id = ids[labels.index(picked)]
    if entity_id != st.session_state.get(_SESSION_ENTITY):
        st.session_state[_SESSION_ENTITY] = entity_id
    return next(row for row in entities if row["id"] == entity_id)

def _run_structure_scan(configured: list[str]) -> None:
    """HTTP-Probe only for mapping names. MCP/Ollama remain in integrations for later re-use."""
    st.session_state.pop(_SESSION_PROPOSALS, None)
    result = scan_structure(
        host=str(config.get("LOXONE_IP") or ""),
        username=str(config.get("LOXONE_USER") or ""),
        password=str(config.get("LOXONE_PASS") or ""),
        configured_names=configured,
        mcp_base_url="",
        sources=(SOURCE_HTTP_PROBE,),
        selected_source=SOURCE_HTTP_PROBE,
    )
    st.session_state["ehal_lox_scan_errors"] = result.all_errors()
    items = result.mapping_items(use_source=SOURCE_HTTP_PROBE)
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
            [item.name for item in items],
            fields=PLANT_FIELDS + EV_FIELDS + FLEX_FIELDS + FILTER_FIELDS,
        )
