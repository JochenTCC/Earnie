"""Entity-centric Loxone → EHAL HITL mapping UI (2.4.k).

Apply/persist helpers live in ``ui.ehal_loxone_mapping_persist``, marker/scan-row
helpers in ``ui.ehal_loxone_markers`` and shared constants in
``ui.ehal_loxone_mapping_base``; all names stay importable from here.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

import config
from ehal.ess_fields import (
    ESS_BATTERY_MAPPING_KINDS,
    ESS_BATTERY_MAPPING_KINDS_BASE,
    ess_field,
    ess_field_kind,
)
from ehal.inverter_fields import INVERTER_MAPPING_KINDS, inv_field, inv_field_kind
from ehal.pv_fields import PV_MAPPING_KINDS, pv_field, pv_field_kind
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
from ehal.field_catalog import (
    TELEMETRY_ENERGY_OPTIONAL,
    TELEMETRY_OPTIONAL_STATIC_HUB as TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
)
from integrations.loxone_ehal_mapping import (
    FIELD_LABELS,
    heuristic_propose,
)
from integrations.loxone_structure import (
    SOURCE_HTTP_PROBE,
    scan_structure,
)
from ui.flash import flash
from ui.house_config_io import get_live_scenario_refs
from ui.ehal_loxone_mapping_base import (  # noqa: F401 — re-exports
    _SESSION_MIGRATED,
    BATTERY_ENTITY_KIND,
    INVERTER_ENTITY_KIND,
    PLANT_ENTITY_ID,
    PV_ENTITY_KIND,
    _nonempty,
)
from ui.ehal_loxone_mapping_persist import (  # noqa: F401 — re-exports
    _migrate_on_open,
    apply_battery_bindings,
    apply_entity_bindings,
    apply_inverter_bindings,
    apply_pv_system_bindings,
    persist_loxone_entity_mapping,
)
from ui.ehal_loxone_markers import (  # noqa: F401 — re-exports
    SCAN_ROW_KEYS,
    _scan_item_fields,
    configured_marker_names,
    device_map_ehal_by_name,
    ehal_name_for_marker,
    enrich_structure_scan_rows,
    marker_to_ehal_lookup,
    structure_scan_row,
)

_NONE = "— nicht gemappt —"
_SESSION_SCAN = "ehal_lox_scan"
_SESSION_PROPOSALS = "ehal_lox_proposals"
_SESSION_ENTITY = "ehal_lox_entity_id"
_SESSION_MANUAL_NAMES = "ehal_lox_manual_names"
_SESSION_MANUAL_FEEDBACK = "ehal_lox_manual_feedback"
_SESSION_PENDING_NEW = "ehal_lox_pending_new_marker"


# Plant mapping no longer owns ESS SoC/power/limits/Quellenwahl (2.7.m / entity-scoped).
_PLANT_ESS_MOVED = frozenset(ESS_BATTERY_MAPPING_KINDS)
PLANT_TELEMETRY_REQUIRED: tuple[str, ...] = tuple(
    f for f in TELEMETRY_REQUIRED if f not in _PLANT_ESS_MOVED
)

PLANT_FIELDS: tuple[str, ...] = (
    PLANT_TELEMETRY_REQUIRED
    + tuple(
        f
        for f in TELEMETRY_OPTIONAL
        if f != "sens_evcs_active_power" and f not in _PLANT_ESS_MOVED
    )
    + TELEMETRY_ENERGY_OPTIONAL
    + ("set_grid_export_power_limit",)
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

# Flat kinds for heuristic_propose (battery rows use entity-scoped at lookup time).
PROPOSAL_FIELDS: tuple[str, ...] = (
    PLANT_FIELDS
    + ESS_BATTERY_MAPPING_KINDS
    + INVERTER_MAPPING_KINDS
    + EV_FIELDS
    + FLEX_FIELDS
    + FILTER_FIELDS
)


def proposal_for_mapping_field(
    proposals: dict[str, dict[str, Any]], field: str
) -> dict[str, Any]:
    """Resolve a proposal for a mapping field (flat or entity-scoped)."""
    entry = proposals.get(field) if isinstance(proposals, dict) else None
    if isinstance(entry, dict):
        return entry
    kind = ess_field_kind(field) or inv_field_kind(field) or pv_field_kind(field)
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
    kind = ess_field_kind(field) or inv_field_kind(field) or pv_field_kind(field)
    if kind and kind in labels:
        return labels[kind]
    return labels.get(field, field)


def _battery_shows_source_select(battery: dict | None) -> bool:
    """Quellenwahl only on physical standby_backup powerstations."""
    from house_config.powerstation import (
        BACKING_PHYSICAL,
        ROLE_STANDBY_BACKUP,
        is_powerstation,
    )

    if not isinstance(battery, dict) or not is_powerstation(battery):
        return False
    if str(battery.get("role") or "") != ROLE_STANDBY_BACKUP:
        return False
    return str(battery.get("backing") or "") == BACKING_PHYSICAL


def fields_for_battery(
    battery_id: str,
    *,
    battery: dict | None = None,
) -> tuple[str, ...]:
    """Entity-scoped ESS mapping fields; Quellenwahl only for physical standby_backup."""
    kinds = (
        ESS_BATTERY_MAPPING_KINDS
        if _battery_shows_source_select(battery)
        else ESS_BATTERY_MAPPING_KINDS_BASE
    )
    return tuple(ess_field(battery_id, kind) for kind in kinds)


def fields_for_inverter(inverter_id: str) -> tuple[str, ...]:
    """Entity-scoped inverter mapping fields (``inv.{id}.*``)."""
    return tuple(inv_field(inverter_id, kind) for kind in INVERTER_MAPPING_KINDS)


def fields_for_pv_system(pv_system_id: str) -> tuple[str, ...]:
    """Entity-scoped PV mapping fields (``pv.{id}.*``)."""
    return tuple(pv_field(pv_system_id, kind) for kind in PV_MAPPING_KINDS)


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




def fields_for_consumer(consumer: dict) -> tuple[str, ...]:
    """EHAL mapping fields for a house-profile consumer type."""
    ctype = str(consumer.get("type") or "").strip()
    if ctype == "ev":
        return EV_FIELDS
    from ehal.flex_fields import consumer_fields_for_consumer

    cid = str(consumer.get("id") or "").strip()
    if cid == "pool_filter":
        return filter_ehal_fields_for_consumer("pool_filter")
    if cid:
        base = consumer_fields_for_consumer(cid, ctype)
    else:
        base = FLEX_FIELDS
    if ctype == "thermal_rc":
        return base + THERMAL_RC_EHAL_FIELDS
    if ctype == "thermal_annual":
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


def _entity_rows(
    items: list,
    *,
    kind: str,
    entity_key: str | None,
    fields_for,
) -> list[dict[str, Any]]:
    """Mapping rows for entities with an ``id`` (others are skipped)."""
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entity_id = _nonempty(item.get("id"))
        if not entity_id:
            continue
        row: dict[str, Any] = {
            "id": entity_id,
            "kind": kind,
            "label": _nonempty(item.get("label")) or entity_id,
            "fields": fields_for(entity_id, item),
            "bindings": binding_map(item.get("ehal_bindings")),
        }
        if entity_key is not None:
            row[entity_key] = item
        rows.append(row)
    return rows


def _component_list(components: object, key: str) -> list:
    raw = components.get(key) if isinstance(components, dict) else None
    return raw if isinstance(raw, list) else []


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

    rows.extend(
        _entity_rows(
            ehal_mappable_batteries(components.get("batteries") if isinstance(components, dict) else []),
            kind=BATTERY_ENTITY_KIND,
            entity_key="battery",
            fields_for=lambda bid, battery: fields_for_battery(bid, battery=battery),
        )
    )
    rows.extend(
        _entity_rows(
            _component_list(components, "inverters"),
            kind=INVERTER_ENTITY_KIND,
            entity_key="inverter",
            fields_for=lambda iid, _inverter: fields_for_inverter(iid),
        )
    )
    rows.extend(
        _entity_rows(
            _component_list(components, "pv_systems"),
            kind=PV_ENTITY_KIND,
            entity_key="pv_system",
            fields_for=lambda pid, _pv: fields_for_pv_system(pid),
        )
    )
    rows.extend(
        _entity_rows(
            consumers_for_profile(house_doc, profile_id),
            kind="consumer",
            entity_key="consumer",
            fields_for=lambda _cid, consumer: fields_for_consumer(consumer),
        )
    )
    return rows


def entity_kind_for_id(
    house_doc: dict,
    profile_id: str,
    entity_id: str,
    *,
    components_doc: dict | None = None,
) -> str:
    """Return ``plant`` / ``battery`` / ``inverter`` / ``pv_system`` / ``consumer``."""
    eid = _nonempty(entity_id)
    if eid == PLANT_ENTITY_ID:
        return "plant"
    for row in build_entity_rows(house_doc, profile_id, components_doc=components_doc):
        if _nonempty(row.get("id")) == eid:
            return str(row.get("kind") or "")
    return ""


















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
            kind = ess_field_kind(field)
            prop = (
                {}
                if kind == "set_ess_source_select" or field == "set_ess_source_select"
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
    flash("success", f"Mapping für `{entity_id}` gespeichert — {detail}.")
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
