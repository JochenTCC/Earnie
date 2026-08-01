"""Entity-centric Loxone → EHAL HITL mapping UI (2.4.k)."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from ehal.profiles import group_fields_by_role, role_field_labels, role_group_label
from house_config.ehal_bindings import (
    FILTER_EHAL_FIELDS,
    FILTER_ENTITY_ID,
    ehal_map_to_filter_bindings,
    ensure_migrated,
    filter_bindings_to_ehal_map,
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
}


def _field_label(field: str) -> str:
    from ehal.flex_fields import flex_field_label

    labels = {**role_field_labels(), **FIELD_LABELS, **_EXTRA_LABELS}
    pattern_label = flex_field_label(field)
    if pattern_label:
        return pattern_label
    return labels.get(field, field)


def _field_select_caption(
    field: str,
    *,
    required: bool = False,
    confidence: float | None = None,
) -> str:
    """Bedeutung + EHAL value name for HITL select labels."""
    meaning = _field_label(field)
    suffix = " *" if required else ""
    conf = f" (Konfidenz {confidence:.0%})" if confidence is not None else ""
    return f"{meaning} (`{field}`){suffix}{conf}"


def _nonempty(value: object) -> str:
    return str(value or "").strip()


def fields_for_consumer(consumer: dict) -> tuple[str, ...]:
    """EHAL mapping fields for a house-profile consumer type."""
    if str(consumer.get("type") or "") == "ev":
        return EV_FIELDS
    from ehal.flex_fields import flex_fields_for_consumer

    cid = str(consumer.get("id") or "").strip()
    if cid:
        return flex_fields_for_consumer(cid)
    return FLEX_FIELDS


def _milp_thermal_rc_host(consumers: list[dict]) -> dict | None:
    """First thermal_rc that creates the SwimSpa-filter bridge entity."""
    from house_config.consumption_csv import consumer_uses_profile_csv

    for consumer in consumers:
        if str(consumer.get("type") or "") != "thermal_rc":
            continue
        if consumer_uses_profile_csv(consumer):
            continue
        return consumer
    return None


def binding_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): _nonempty(v) for k, v in raw.items() if _nonempty(v)}


def resolve_live_profile_id(house_doc: dict) -> str:
    """Prefer Live-Szenario house_profile_id; else first profile id."""
    refs = get_live_scenario_refs()
    profile_id = _nonempty(refs.get("house_profile_id"))
    profiles = house_doc.get("profiles") or {}
    if isinstance(profiles, dict):
        if profile_id and profile_id in profiles:
            return profile_id
        return next(iter(profiles), "")
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict) and _nonempty(profile.get("id")) == profile_id:
                return profile_id
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("id"):
                return str(profile["id"])
    return ""


def consumers_for_profile(house_doc: dict, profile_id: str) -> list[dict]:
    profiles = house_doc.get("profiles") or {}
    if isinstance(profiles, dict):
        profile = profiles.get(profile_id) if profile_id else None
    elif isinstance(profiles, list):
        profile = next(
            (
                p
                for p in profiles
                if isinstance(p, dict) and str(p.get("id") or "") == profile_id
            ),
            None,
        )
    else:
        profile = None
    if not isinstance(profile, dict):
        return []
    raw = profile.get("consumers") or []
    return [c for c in raw if isinstance(c, dict)]


def build_entity_rows(house_doc: dict, profile_id: str) -> list[dict[str, Any]]:
    """Plant + live-profile consumers as mapping entity rows."""
    plant = house_doc.get("plant") if isinstance(house_doc.get("plant"), dict) else {}
    rows: list[dict[str, Any]] = [
        {
            "id": PLANT_ENTITY_ID,
            "kind": "plant",
            "label": "Anlage (Plant)",
            "fields": PLANT_FIELDS,
            "bindings": binding_map(plant.get("ehal_bindings")),
        }
    ]
    consumers = consumers_for_profile(house_doc, profile_id)
    for consumer in consumers:
        cid = _nonempty(consumer.get("id"))
        if not cid:
            continue
        rows.append(
            {
                "id": cid,
                "kind": "consumer",
                "label": _nonempty(consumer.get("label")) or cid,
                "fields": fields_for_consumer(consumer),
                "bindings": binding_map(consumer.get("ehal_bindings")),
                "consumer": consumer,
            }
        )
    host = _milp_thermal_rc_host(consumers)
    if host is not None and not any(
        str(c.get("id") or "").strip() == "pool_filter" for c in consumers
    ):
        stored = host.get("swimspa_filter_bindings")
        rows.append(
            {
                "id": FILTER_ENTITY_ID,
                "kind": "filter",
                "label": "Pool / SwimSpa Filter",
                "fields": FILTER_FIELDS,
                "bindings": filter_bindings_to_ehal_map(
                    stored if isinstance(stored, dict) else {}
                ),
                "host_id": _nonempty(host.get("id")),
            }
        )
    return rows


def apply_entity_bindings(
    house_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    bindings: dict[str, str],
) -> dict:
    """Write bindings onto plant, consumer, or filter bridge nest; return new doc."""
    house = dict(house_doc)
    cleaned = {k: v for k, v in bindings.items() if _nonempty(v)}
    if entity_id == PLANT_ENTITY_ID:
        plant = dict(house.get("plant") or {}) if isinstance(house.get("plant"), dict) else {}
        plant["ehal_bindings"] = cleaned
        plant.pop("event_triggers", None)
        house["plant"] = plant
        return house
    profiles = house.get("profiles")
    if not isinstance(profiles, dict):
        return house
    profile = dict(profiles.get(profile_id) or {})
    consumers = [dict(c) for c in (profile.get("consumers") or []) if isinstance(c, dict)]
    if entity_id == FILTER_ENTITY_ID:
        host = _milp_thermal_rc_host(consumers)
        host_id = _nonempty(host.get("id")) if host else ""
        nest = ehal_map_to_filter_bindings(cleaned)
        for consumer in consumers:
            if _nonempty(consumer.get("id")) != host_id:
                continue
            if nest:
                consumer["swimspa_filter_bindings"] = nest
            else:
                consumer.pop("swimspa_filter_bindings", None)
            break
        profile["consumers"] = consumers
        house["profiles"] = {**profiles, profile_id: profile}
        return house
    for consumer in consumers:
        if _nonempty(consumer.get("id")) == entity_id:
            consumer["ehal_bindings"] = cleaned
            consumer.pop("event_triggers", None)
            break
    profile["consumers"] = consumers
    house["profiles"] = {**profiles, profile_id: profile}
    return house


def configured_marker_names(house_doc: dict, profile_id: str) -> list[str]:
    names: list[str] = []
    for row in build_entity_rows(house_doc, profile_id):
        names.extend(v for v in row["bindings"].values() if v)
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
    key: str,
) -> str:
    choice = current if current in options else _NONE
    selected = st.selectbox(
        _field_select_caption(field, required=required, confidence=confidence),
        options=options,
        index=options.index(choice) if choice in options else 0,
        key=key,
    )
    return "" if selected == _NONE else str(selected)


def _migrate_on_open() -> tuple[dict, dict]:
    """Ensure entity bindings exist; persist house + stripped config once when changed."""
    house = load_house_profiles()
    config_doc = load_main_config()
    new_house, new_config, changed = ensure_migrated(house, config_doc)
    if changed and not st.session_state.get(_SESSION_MIGRATED):
        save_house_profiles(new_house)
        stripped = strip_migrated_config_keys(new_config)
        save_main_config(stripped)
        reset_adapter_cache()
        st.session_state[_SESSION_MIGRATED] = True
        return new_house, stripped
    return new_house if changed else house, config_doc


def render_ehal_loxone_mapping_section() -> None:
    """HTTP-probe structure scan + entity HITL; persists plant/consumer ehal_bindings."""
    st.caption(
        "Entity-zentriertes Mapping: Anlage + Verbraucher aus dem Live-Hausprofil. "
        "Bei MILP-`thermal_rc` zusätzlich Entity **Pool / SwimSpa Filter** "
        f"(`{FILTER_ENTITY_ID}`) für `get_filter_remaining_hours` u. a. "
        "Felder `{entity}.{ehal_field}` → Merker; Speichern in `house_profiles.json` "
        "(`plant` / `consumers[].ehal_bindings` / `swimspa_filter_bindings`). "
        "Außerplanmäßige Optimierung: Loxone VO `Earnie_Request_Optimize` "
        "(Daemon-HTTP, Port `system.ehal_loxone_http_port`, Standard 8541). "
        "Struktur-Scan: HTTP-Probe bekannter Earnie_*/gemappter Merker."
    )
    house, config_doc = _migrate_on_open()
    profile_id = resolve_live_profile_id(house)
    entities = build_entity_rows(house, profile_id)
    if not profile_id:
        st.warning("Kein Hausprofil im Live-Szenario — bitte zuerst im Szenarienkonfigurator setzen.")
        return
    rows = _render_http_probe_scan(house, profile_id)
    entity = _render_entity_picker(entities)
    proposals: dict[str, dict[str, Any]] = dict(st.session_state.get(_SESSION_PROPOSALS) or {})
    options = _name_options(rows, list(entity["bindings"].values()))
    ehal_map = _render_field_selects(entity, options, proposals)
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
        _run_structure_scan(configured_marker_names(house, profile_id))
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


def _render_entity_picker(entities: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [f"{row['label']} (`{row['id']}`)" for row in entities]
    ids = [str(row["id"]) for row in entities]
    current = str(st.session_state.get(_SESSION_ENTITY) or PLANT_ENTITY_ID)
    if current not in ids:
        current = ids[0] if ids else PLANT_ENTITY_ID
    picked = st.selectbox(
        "Entity",
        options=labels,
        index=ids.index(current) if current in ids else 0,
        key="ehal_lox_entity_pick",
    )
    entity_id = ids[labels.index(picked)]
    if entity_id != st.session_state.get(_SESSION_ENTITY):
        st.session_state[_SESSION_ENTITY] = entity_id
    return next(row for row in entities if row["id"] == entity_id)


def _render_field_selects(
    entity: dict[str, Any],
    options: list[str],
    proposals: dict[str, dict[str, Any]],
) -> dict[str, str]:
    ehal_map: dict[str, str] = {}
    bindings = entity["bindings"]
    fields: tuple[str, ...] = tuple(entity["fields"])
    required = set(TELEMETRY_REQUIRED) if entity["id"] == PLANT_ENTITY_ID else set()
    grouped = group_fields_by_role(fields)
    if not grouped:
        grouped = [("other", list(fields))]
    for role_id, role_fields in grouped:
        caption = role_group_label(role_id) if role_id != "other" else "Felder"
        st.markdown(f"**{caption}** — `{entity['id']}`")
        for field in role_fields:
            prop = proposals.get(field) or {}
            default = str(prop.get("marker_name") or bindings.get(field) or "")
            conf = prop.get("confidence")
            mapped = _select_marker(
                field,
                current=default if default in options else bindings.get(field, ""),
                options=options,
                required=field in required,
                confidence=float(conf) if conf is not None else None,
                key=f"ehal_lox_map_{entity['id']}_{field}",
            )
            if mapped:
                ehal_map[field] = mapped
    return ehal_map


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


def _validate_mapping_save(entity_id: str, ehal_map: dict[str, str]) -> str | None:
    if entity_id == PLANT_ENTITY_ID:
        missing = [name for name in TELEMETRY_REQUIRED if name not in ehal_map]
        if missing:
            return "Pflichtfelder fehlen: " + ", ".join(missing)
    return None


def _ensure_ehal_loxone_meta(config_doc: dict) -> dict:
    stripped = strip_migrated_config_keys(config_doc)
    ehal = dict(stripped.get("ehal") or {}) if isinstance(stripped.get("ehal"), dict) else {}
    if not ehal.get("backend"):
        ehal["backend"] = "loxone"
    if not ehal.get("adapter_id"):
        ehal["adapter_id"] = "loxone-home"
    stripped["ehal"] = ehal
    return stripped


def _save_entity_mapping(
    house: dict,
    config_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    ehal_map: dict[str, str],
) -> None:
    error = _validate_mapping_save(entity_id, ehal_map)
    if error:
        st.error(error)
        return
    migrated_house, migrated_config, _ = ensure_migrated(house, config_doc)
    updated = apply_entity_bindings(
        migrated_house,
        profile_id=profile_id,
        entity_id=entity_id,
        bindings=ehal_map,
    )
    save_house_profiles(updated)
    save_main_config(_ensure_ehal_loxone_meta(migrated_config))
    reset_adapter_cache()
    st.session_state[_SESSION_MIGRATED] = True
    st.success(
        f"Mapping für `{entity_id}` in `house_profiles.json` gespeichert "
        "(Bindings); Legacy-Merker-Trigger und Anlagen-Rollen in config bereinigt."
    )
    st.rerun()
