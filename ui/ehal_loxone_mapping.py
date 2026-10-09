"""Entity-centric Loxone → EHAL HITL mapping UI (2.4.k)."""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from ehal.ess_fields import ESS_BATTERY_MAPPING_KINDS, ess_field, ess_field_kind
from ehal.profiles import group_fields_by_role, role_field_labels, role_group_label
from house_config.ehal_bindings import (
    FILTER_EHAL_FIELDS,
    THERMAL_ANNUAL_EHAL_FIELDS,
    THERMAL_RC_EHAL_FIELDS,
    ensure_migrated,
    filter_ehal_fields_for_consumer,
    strip_migrated_config_keys,
)
from integrations.ehal_live import reset_adapter_cache
from integrations.loxone_ehal_mapping import (
    FIELD_LABELS,
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
BATTERY_ENTITY_KIND = "battery"

# Plant mapping no longer owns ESS SoC/power/limits (2.7.m); shared EcoFlow bridge stays.
_PLANT_ESS_MOVED = frozenset(ESS_BATTERY_MAPPING_KINDS)
PLANT_TELEMETRY_REQUIRED: tuple[str, ...] = tuple(
    f for f in TELEMETRY_REQUIRED if f not in _PLANT_ESS_MOVED
)
_PLANT_ENERGY_OPTIONAL: tuple[str, ...] = (
    "sens_pv_energy",
    "sens_grid_energy_import",
    "sens_grid_energy_export",
)

PLANT_FIELDS: tuple[str, ...] = (
    PLANT_TELEMETRY_REQUIRED
    + tuple(
        f
        for f in TELEMETRY_OPTIONAL
        if f != "sens_evcs_active_power" and f not in _PLANT_ESS_MOVED
    )
    + _PLANT_ENERGY_OPTIONAL
    + ("set_ess_source_select", "set_grid_export_power_limit")
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
    "flex.sens_consumer_active",
    "flex.set_enable",
    "sens_energy_total",
)

FILTER_FIELDS: tuple[str, ...] = FILTER_EHAL_FIELDS

# Flat kinds for heuristic_propose (battery rows use Pattern B at lookup time).
PROPOSAL_FIELDS: tuple[str, ...] = (
    PLANT_FIELDS + ESS_BATTERY_MAPPING_KINDS + EV_FIELDS + FLEX_FIELDS + FILTER_FIELDS
)


def proposal_for_mapping_field(
    proposals: dict[str, dict[str, Any]], field: str
) -> dict[str, Any]:
    """Resolve a proposal for a mapping field (flat or Pattern B ``ess.<id>.<kind>``)."""
    entry = proposals.get(field) if isinstance(proposals, dict) else None
    if isinstance(entry, dict):
        return entry
    kind = ess_field_kind(field)
    if kind:
        entry = proposals.get(kind)
        if isinstance(entry, dict):
            return entry
    return {}


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
    "flex.sens_power_act": "Flex Leistung / Zustand",
    "flex.sens_consumer_active": "Gerät läuft (Binär)",
    "flex.set_enable": "Flex Freigabe",
    "get_filter_remaining_hours": "Filter Sollstunden (h)",
    "sens_filter_active": "Filter läuft (Binär)",
    "get_filter_native_start_hour": "Native Filter-Startstunde",
    "get_filter_native_duration_hours": "Native Filter-Dauer (h)",
    "sens_temperature_water": "Pool Ist-Temperatur (°C)",
    "get_temperature_water_setpoint": "Pool Soll-Temperatur (°C)",
    "get_temperature_tolerance_c": "Temperatur-Toleranz (°C)",
    "sens_heating_active": "Heizung aktiv",
    "sens_temperature_heat_storage": "Wärmespeicher T_eq (°C)",
    "sens_temperature_heat_storage_low": "Wärmespeicher T_low (°C)",
    "sens_temperature_outside": "Außentemperatur (°C)",
    "sens_absent_mode": "Abwesend / Urlaub (0/1)",
}


def _field_label(field: str) -> str:
    from ehal.flex_fields import flex_field_label

    labels = {**role_field_labels(), **FIELD_LABELS, **_EXTRA_LABELS}
    pattern_label = flex_field_label(field)
    if pattern_label:
        return pattern_label
    kind = ess_field_kind(field)
    if kind and kind in labels:
        return labels[kind]
    return labels.get(field, field)


def fields_for_battery(battery_id: str) -> tuple[str, ...]:
    """Pattern B ESS mapping fields for one battery (excludes shared source_select)."""
    return tuple(ess_field(battery_id, kind) for kind in ESS_BATTERY_MAPPING_KINDS)


def _load_components_for_mapping() -> dict:
    try:
        from ui.house_config_io import _load_components_document

        doc = _load_components_document()
        return doc if isinstance(doc, dict) else {"batteries": [], "pv_systems": []}
    except Exception:
        return {"batteries": [], "pv_systems": []}


def _field_select_caption(
    field: str,
    *,
    required: bool = False,
) -> str:
    """Bedeutung + EHAL value name for HITL select labels."""
    meaning = _field_label(field)
    suffix = " *" if required else ""
    return f"{meaning} (`{field}`){suffix}"


def _nonempty(value: object) -> str:
    return str(value or "").strip()


def fields_for_consumer(consumer: dict) -> tuple[str, ...]:
    """EHAL mapping fields for a house-profile consumer type."""
    if str(consumer.get("type") or "") == "ev":
        return EV_FIELDS
    from ehal.flex_fields import flex_fields_for_consumer

    cid = str(consumer.get("id") or "").strip()
    if cid == "pool_filter":
        return filter_ehal_fields_for_consumer("pool_filter")
    if cid:
        base = flex_fields_for_consumer(cid)
    else:
        base = FLEX_FIELDS
    if str(consumer.get("type") or "") == "thermal_rc":
        return base + THERMAL_RC_EHAL_FIELDS
    if str(consumer.get("type") or "") == "thermal_annual":
        return base + THERMAL_ANNUAL_EHAL_FIELDS
    return base


def binding_map(raw: object) -> dict[str, str]:
    """Activated Loxone bindings; empty string values are activation flags (Q8)."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        field = str(key or "").strip()
        if field:
            out[field] = _nonempty(value)
    return out


def resolve_field_select_default(existing: str, proposed: str) -> str:
    """Prefer saved binding; use heuristic proposal only when unbound."""
    return str(existing or proposed or "")


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


def build_entity_rows(
    house_doc: dict,
    profile_id: str,
    *,
    components_doc: dict | None = None,
) -> list[dict[str, Any]]:
    """Plant + batteries + live-profile consumers as mapping entity rows."""
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
    components = (
        components_doc
        if isinstance(components_doc, dict)
        else _load_components_for_mapping()
    )
    from house_config.powerstation import ehal_mappable_batteries

    for battery in ehal_mappable_batteries(
        components.get("batteries") if isinstance(components, dict) else []
    ):
        bid = _nonempty(battery.get("id"))
        if not bid:
            continue
        rows.append(
            {
                "id": bid,
                "kind": BATTERY_ENTITY_KIND,
                "label": _nonempty(battery.get("label")) or bid,
                "fields": fields_for_battery(bid),
                "bindings": binding_map(battery.get("ehal_bindings")),
                "battery": battery,
            }
        )
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
    return rows


def apply_entity_bindings(
    house_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    bindings: dict[str, str],
) -> dict:
    """Write bindings onto plant or consumer; return new doc.

    Battery entities use :func:`apply_battery_bindings` (components.json).
    """
    house = dict(house_doc)
    # Q8: keep keys with empty Merker as activation flags.
    cleaned = {
        str(k): _nonempty(v) for k, v in bindings.items() if str(k or "").strip()
    }
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
    for consumer in consumers:
        if _nonempty(consumer.get("id")) == entity_id:
            consumer["ehal_bindings"] = cleaned
            consumer.pop("event_triggers", None)
            break
    profile["consumers"] = consumers
    house["profiles"] = {**profiles, profile_id: profile}
    return house


def apply_battery_bindings(
    components_doc: dict,
    *,
    battery_id: str,
    bindings: dict[str, str],
) -> dict:
    """Write Pattern B ESS bindings onto ``batteries[].ehal_bindings``.

    Refuses virtual powerstations (no EHAL binding surface).
    """
    from copy import deepcopy

    from house_config.powerstation import is_virtual_powerstation

    out = deepcopy(components_doc) if isinstance(components_doc, dict) else {
        "batteries": [],
        "pv_systems": [],
    }
    batteries = out.get("batteries")
    if not isinstance(batteries, list):
        batteries = []
        out["batteries"] = batteries
    cleaned = {
        str(k): _nonempty(v) for k, v in bindings.items() if str(k or "").strip()
    }
    bid = _nonempty(battery_id)
    found = False
    for index, battery in enumerate(batteries):
        if not isinstance(battery, dict):
            continue
        if _nonempty(battery.get("id")) != bid:
            continue
        if is_virtual_powerstation(battery):
            raise ValueError(
                f"Virtual powerstation '{bid}' has no EHAL bindings "
                "(inherits house ESS; map the house battery instead)."
            )
        updated = dict(battery)
        updated["ehal_bindings"] = cleaned
        batteries[index] = updated
        found = True
        break
    if not found and bid:
        batteries.append({"id": bid, "label": bid, "ehal_bindings": cleaned})
    return out


def entity_kind_for_id(
    house_doc: dict,
    profile_id: str,
    entity_id: str,
    *,
    components_doc: dict | None = None,
) -> str:
    """Return ``plant`` / ``battery`` / ``consumer`` / ```` for an entity id."""
    eid = _nonempty(entity_id)
    if eid == PLANT_ENTITY_ID:
        return "plant"
    for row in build_entity_rows(house_doc, profile_id, components_doc=components_doc):
        if _nonempty(row.get("id")) == eid:
            return str(row.get("kind") or "")
    return ""


def configured_marker_names(house_doc: dict, profile_id: str) -> list[str]:
    names: list[str] = []
    for row in build_entity_rows(house_doc, profile_id):
        names.extend(v for v in row["bindings"].values() if v)
    return names


# HTTP-Probe Mapping-Tabelle column order (uuid/room/category far right).
SCAN_ROW_KEYS: tuple[str, ...] = (
    "name",
    "ehal",
    "type",
    "source",
    "room",
    "category",
    "uuid",
)


def marker_to_ehal_lookup(house_doc: dict, profile_id: str) -> dict[str, str]:
    """Reverse map Merker title → EHAL binding key from plant + consumers."""
    out: dict[str, str] = {}
    for row in build_entity_rows(house_doc, profile_id):
        bindings = row.get("bindings") or {}
        if not isinstance(bindings, dict):
            continue
        for field, merker in bindings.items():
            name = _nonempty(merker)
            if name and name not in out:
                out[name] = str(field)
    return out


def device_map_ehal_by_name(device_map: dict[str, Any] | None = None) -> dict[str, str]:
    """Exact greenfield marker name → ehal_field (skips null/empty)."""
    from integrations.loxone_greenfield_import import load_device_map

    dmap = device_map if device_map is not None else load_device_map()
    out: dict[str, str] = {}
    for marker in dmap.get("markers") or []:
        if not isinstance(marker, dict):
            continue
        name = _nonempty(marker.get("name"))
        field = marker.get("ehal_field")
        if not name or field is None:
            continue
        field_s = _nonempty(field)
        if field_s:
            out[name] = field_s
    return out


def ehal_name_for_marker(
    name: str,
    house_doc: dict,
    profile_id: str,
    *,
    bindings_lookup: dict[str, str] | None = None,
    device_lookup: dict[str, str] | None = None,
) -> str:
    """Resolve EHAL wire name for a Merker: house binding first, else device map."""
    key = _nonempty(name)
    if not key:
        return ""
    reverse = (
        bindings_lookup
        if bindings_lookup is not None
        else marker_to_ehal_lookup(house_doc, profile_id)
    )
    if key in reverse:
        return reverse[key]
    dmap = device_lookup if device_lookup is not None else device_map_ehal_by_name()
    return dmap.get(key, "")


def structure_scan_row(
    *,
    name: str,
    ehal: str = "",
    type_: str = "",
    source: str = "",
    room: str = "",
    category: str = "",
    uuid: str = "",
) -> dict[str, str]:
    """Ordered Mapping-Tabelle row dict."""
    return {
        "name": name,
        "ehal": ehal,
        "type": type_,
        "source": source,
        "room": room,
        "category": category,
        "uuid": uuid,
    }


def enrich_structure_scan_rows(
    items: list[Any],
    house_doc: dict,
    profile_id: str,
) -> list[dict[str, str]]:
    """Build ordered scan rows with ehal resolved from house / device map."""
    reverse = marker_to_ehal_lookup(house_doc, profile_id)
    try:
        dmap = device_map_ehal_by_name()
    except (OSError, ValueError, FileNotFoundError):
        dmap = {}
    rows: list[dict[str, str]] = []
    for item in items:
        name, type_, source, room, category, uuid = _scan_item_fields(item)
        ehal = ehal_name_for_marker(
            name,
            house_doc,
            profile_id,
            bindings_lookup=reverse,
            device_lookup=dmap,
        )
        rows.append(
            structure_scan_row(
                name=name,
                ehal=ehal,
                type_=type_,
                source=source,
                room=room,
                category=category,
                uuid=uuid,
            )
        )
    return rows


def _scan_item_fields(item: Any) -> tuple[str, str, str, str, str, str]:
    """Extract name/type/source/room/category/uuid from StructureItem or dict."""
    keys = ("name", "type", "source", "room", "category", "uuid")
    if isinstance(item, dict):
        vals = [_nonempty(item.get(k)) for k in keys]
    else:
        vals = [_nonempty(getattr(item, k, "")) for k in keys]
    return (vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])


def session_manual_marker_names() -> list[str]:
    """Session-only Merker names typed in on EHAL-Com (not yet necessarily saved)."""
    raw = st.session_state.get(_SESSION_MANUAL_NAMES) or []
    return [str(n).strip() for n in raw if str(n or "").strip()]


def add_manual_marker_name(
    existing: list[str],
    raw: str,
    *,
    also_known: list[str] | None = None,
) -> tuple[list[str], str | None]:
    """Append a stripped Merker name; return (list, hint) — hint set on empty/duplicate."""
    name = str(raw or "").strip()
    if not name:
        return list(existing), "Leerer Merkername — nichts hinzugefügt."
    key = name.casefold()
    known = list(existing) + list(also_known or [])
    if any(str(n).strip().casefold() == key for n in known if str(n or "").strip()):
        return list(existing), f"`{name}` ist bereits in der Liste."
    return [*existing, name], None


def is_known_marker_name(name: str, options: list[str]) -> bool:
    """True if name matches a non-sentinel option (case-insensitive)."""
    key = str(name or "").strip().casefold()
    if not key or key == _NONE.casefold():
        return False
    return any(
        str(o).strip().casefold() == key for o in options if str(o or "").strip() and o != _NONE
    )


def _name_options(
    rows: list[dict[str, Any]],
    current_values: list[str],
    manual_names: list[str] | None = None,
) -> list[str]:
    names = [str(row.get("name") or "") for row in rows if str(row.get("name") or "").strip()]
    for value in list(current_values) + list(manual_names or []):
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text)
    names.sort(key=str.lower)
    return [_NONE] + names




def _clear_pending_for_widget(widget_key: str) -> None:
    pending = st.session_state.get(_SESSION_PENDING_NEW)
    if isinstance(pending, dict) and pending.get("widget_key") == widget_key:
        st.session_state.pop(_SESSION_PENDING_NEW, None)


def _queue_pending_new_marker(
    *,
    entity_id: str,
    profile_id: str,
    field: str,
    name: str,
    widget_key: str,
) -> None:
    st.session_state[_SESSION_PENDING_NEW] = {
        "entity_id": entity_id,
        "profile_id": profile_id,
        "field": field,
        "name": name,
        "widget_key": widget_key,
    }


def _migrate_on_open() -> tuple[dict, dict]:
    """Ensure entity bindings exist; persist house + stripped config once when changed."""
    from runtime_store.shadow.mode import is_shadow_mode

    house = load_house_profiles()
    config_doc = load_main_config()
    new_house, new_config, changed = ensure_migrated(house, config_doc)
    if changed and not st.session_state.get(_SESSION_MIGRATED):
        stripped = strip_migrated_config_keys(new_config)
        if is_shadow_mode():
            # Prod config is read-only; keep migrated values in this session only.
            st.session_state[_SESSION_MIGRATED] = True
            return new_house, stripped
        save_house_profiles(new_house)
        save_main_config(stripped)
        reset_adapter_cache()
        st.session_state[_SESSION_MIGRATED] = True
        return new_house, stripped
    return new_house if changed else house, config_doc


def persist_loxone_entity_mapping(
    house: dict,
    config_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    ehal_map: dict[str, str],
    entity_kind: str = "",
) -> str:
    """Persist entity bindings; Shadow → runtime overlay, else house/components + config.

    Returns a short success detail (where data was written).
    """
    from runtime_store.shadow.ehal_overlay import upsert_entity_bindings
    from runtime_store.shadow.mode import is_shadow_mode
    from ui.house_config_io import _load_components_document, _save_components_document

    migrated_house, migrated_config, _ = ensure_migrated(house, config_doc)
    kind = str(entity_kind or "").strip() or entity_kind_for_id(
        migrated_house, profile_id, entity_id
    )
    if is_shadow_mode():
        path = upsert_entity_bindings(
            profile_id=profile_id,
            entity_id=entity_id,
            bindings=ehal_map,
            entity_kind=kind,
        )
        reset_adapter_cache()
        return f"Shadow-Overlay `{path}` (Prod-Config unverändert)"
    if kind == BATTERY_ENTITY_KIND:
        components = apply_battery_bindings(
            _load_components_document(),
            battery_id=entity_id,
            bindings=ehal_map,
        )
        _save_components_document(components)
        save_main_config(_ensure_ehal_loxone_meta(migrated_config))
        reset_adapter_cache()
        return "`components.json` (`batteries[].ehal_bindings`)"
    updated = apply_entity_bindings(
        migrated_house,
        profile_id=profile_id,
        entity_id=entity_id,
        bindings=ehal_map,
    )
    save_house_profiles(updated)
    save_main_config(_ensure_ehal_loxone_meta(migrated_config))
    reset_adapter_cache()
    return (
        "`house_profiles.json` (Bindings); Legacy-Merker-Trigger und "
        "Anlagen-Rollen in config bereinigt"
    )














def _render_field_selects(
    entity: dict[str, Any],
    options: list[str],
    proposals: dict[str, dict[str, Any]],
    *,
    profile_id: str,
) -> dict[str, str]:
    ehal_map: dict[str, str] = {}
    bindings = entity["bindings"]
    fields: tuple[str, ...] = tuple(entity["fields"])
    required: set[str] = set()
    if entity["id"] == PLANT_ENTITY_ID:
        required = set(PLANT_TELEMETRY_REQUIRED)
    elif str(entity.get("kind") or "") == BATTERY_ENTITY_KIND:
        required = {ess_field(str(entity["id"]), "sens_ess_soc")}
    grouped = group_fields_by_role(fields)
    if not grouped:
        grouped = [("other", list(fields))]
    entity_id = str(entity["id"])
    for role_id, role_fields in grouped:
        caption = role_group_label(role_id) if role_id != "other" else "Felder"
        st.markdown(f"**{caption}** — `{entity_id}`")
        for field in role_fields:
            # Quellenwahl is opt-in (standby_backup); never pre-fill from heuristics.
            prop = (
                {}
                if field == "set_ess_source_select"
                else proposal_for_mapping_field(proposals, field)
            )
            existing = str(bindings.get(field) or "")
            proposed = str(prop.get("marker_name") or "")
            default = resolve_field_select_default(existing, proposed)
            mapped = _select_marker(
                field,
                entity_id=entity_id,
                profile_id=profile_id,
                current=default if default in options else bindings.get(field, ""),
                options=options,
                required=field in required,
                key=f"ehal_lox_map_{entity_id}_{field}",
            )
            if mapped:
                ehal_map[field] = mapped
    return ehal_map




def _validate_mapping_save(
    entity_id: str,
    ehal_map: dict[str, str],
    *,
    entity_kind: str = "",
) -> str | None:
    kind = str(entity_kind or "").strip()
    if entity_id == PLANT_ENTITY_ID or kind == "plant":
        missing = [name for name in PLANT_TELEMETRY_REQUIRED if name not in ehal_map]
        if missing:
            return "Pflichtfelder fehlen: " + ", ".join(missing)
        return None
    if kind == BATTERY_ENTITY_KIND:
        soc = ess_field(entity_id, "sens_ess_soc")
        if soc not in ehal_map:
            return f"Pflichtfelder fehlen: {soc}"
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
    entity_kind: str = "",
) -> None:
    kind = str(entity_kind or "").strip() or entity_kind_for_id(
        house, profile_id, entity_id
    )
    error = _validate_mapping_save(entity_id, ehal_map, entity_kind=kind)
    if error:
        st.error(error)
        return
    detail = persist_loxone_entity_mapping(
        house,
        config_doc,
        profile_id=profile_id,
        entity_id=entity_id,
        ehal_map=ehal_map,
        entity_kind=kind,
    )
    st.session_state[_SESSION_MIGRATED] = True
    st.success(f"Mapping für `{entity_id}` gespeichert — {detail}.")
    st.rerun()

from ui.ehal_loxone_mapping_ui import (  # noqa: E402
    PLANT_ENTITY_ID,
    _NONE,
    _SESSION_ENTITY,
    _SESSION_MANUAL_FEEDBACK,
    _SESSION_MANUAL_NAMES,
    _SESSION_MIGRATED,
    _SESSION_PENDING_NEW,
    _SESSION_PROPOSALS,
    _SESSION_SCAN,
    _accept_pending_new_marker,
    _confirm_new_marker_dialog,
    _manual_add_probe_caption,
    _render_entity_picker,
    _render_http_probe_scan,
    _run_structure_scan,
    _select_marker,
    render_ehal_loxone_mapping_section,
)
