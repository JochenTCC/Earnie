"""Batterie-Tab im Hauskonfigurator."""
from __future__ import annotations

import copy
import os

import streamlit as st

from house_config.id_slug import slug_id
from house_config.label_uniqueness import allocate_unique_label
from house_config.battery_control import (
    BATTERY_CONTROL_VALUES,
    CONTROL_LABELS_DE,
    DEFAULT_BATTERY_CONTROL,
)
from house_config.battery_kind import (
    BATTERY_KIND_BATTERY_INVERTER,
    BATTERY_KIND_ISOLATED,
    DEFAULT_BATTERY_KIND,
)
from house_config.powerstation import (
    BACKING_VIRTUAL,
    primary_house_battery,
    virtual_powerstation_fill_fields,
)

KIND_LABELS_DE = {
    BATTERY_KIND_BATTERY_INVERTER: "Batterie + Wechselrichter",
    BATTERY_KIND_ISOLATED: "Isolierte Batterie",
}
_KIND_VALUES = (BATTERY_KIND_BATTERY_INVERTER, BATTERY_KIND_ISOLATED)
from runtime_store.persist_paths import resolve_config_json_path
from ui.house_config_io import (
    delete_battery,
    get_live_scenario_refs,
    list_batteries,
    upsert_battery,
)
from ui.auto_persist import auto_persist, payload_fingerprint
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
    labeled_checkbox,
    labeled_multiselect,
    labeled_number_input,
    labeled_selectbox,
    labeled_text_input,
)
from ui.label_select import (
    NEW_OPTION,
    align_label_select_session,
    label_select_choices,
    resolve_label_select,
)

_SESSION_SYNC_KEY = "planning_battery_sync_id"
_SESSION_FILE_STAMP_KEY = "planning_battery_file_stamp"
_SESSION_SELECT_PENDING_KEY = "planning_battery_select_pending"
_SESSION_SELECTED_ID_KEY = "planning_battery_selected_id"
_SESSION_SUPPRESS_AUTOPERSIST_KEY = "planning_battery_suppress_autopersist"
_SESSION_TEMPLATE_SOURCE_KEY = "planning_battery_template_source"


def new_battery_template(
    batteries: list[dict],
    *,
    source_id: str = "",
    live_battery_id: str = "",
) -> dict:
    """Defaults for a new battery — clone last selected (else Live), else {}."""
    by_id = {
        str(item.get("id", "")).strip(): item
        for item in batteries
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    source = by_id.get(str(source_id or "").strip()) or by_id.get(
        str(live_battery_id or "").strip()
    )
    if source is None:
        return {}

    source_label = str(source.get("label") or source.get("id") or "Batterie").strip()
    from house_config.entity_resolution import split_battery_max_power_kw

    charge_kw, discharge_kw = split_battery_max_power_kw(source, battery_id="template")
    return {
        "label": allocate_unique_label(f"{source_label} copy", batteries),
        "battery_capacity_kwh": float(source.get("battery_capacity_kwh", 5.0)),
        "battery_max_charge_power_kw": charge_kw,
        "battery_max_discharge_power_kw": discharge_kw,
        "battery_efficiency": float(source.get("battery_efficiency", 0.97)),
        "battery_min_soc": float(source.get("battery_min_soc", 10.0)),
        "battery_max_soc": float(source.get("battery_max_soc", 100.0)),
        "threshold_power": float(source.get("threshold_power", 0.05)),
        "standby_power_kw": float(source.get("standby_power_kw", 0.0) or 0.0),
        "kind": str(source.get("kind") or DEFAULT_BATTERY_KIND).strip().lower()
        or DEFAULT_BATTERY_KIND,
        "control": str(source.get("control") or "full").strip().lower() or "full",
        "limits_from_live": bool(source.get("limits_from_live", False)),
        "ehal_bindings": dict(source.get("ehal_bindings") or {}),
        "battery_wear": copy.deepcopy(dict(source.get("battery_wear") or {})),
    }


def _remember_battery_template_source(entity_id: str) -> None:
    sid = str(entity_id or "").strip()
    if sid and sid != NEW_OPTION:
        st.session_state[_SESSION_TEMPLATE_SOURCE_KEY] = sid


def _scoped_key(session_scope: str, base: str) -> str:
    return f"{session_scope}__{base}"


def _battery_session_scope(selected_id: str, *, is_new: bool) -> str:
    return "__new__" if is_new else selected_id


def _config_file_stamp() -> str:
    path = resolve_config_json_path()
    try:
        return f"{os.path.abspath(path)}:{os.path.getmtime(path)}"
    except OSError:
        return os.path.abspath(path)


def _clear_scoped_widget_keys(session_scope: str) -> None:
    prefix = f"{session_scope}__"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            del st.session_state[key]


def _seed_battery_widget_state(session_scope: str, existing: dict) -> None:
    from house_config.entity_resolution import split_battery_max_power_kw

    if existing:
        label = str(existing.get("label", "5 kWh Speicher"))
        capacity = float(existing.get("battery_capacity_kwh", 5.0))
        max_charge, max_discharge = split_battery_max_power_kw(existing)
        efficiency = float(existing.get("battery_efficiency", 0.97))
        min_soc = float(existing.get("battery_min_soc", 10.0))
        max_soc = float(existing.get("battery_max_soc", 100.0))
        threshold_percent = float(existing.get("threshold_power", 0.05)) * 100.0
        standby_power = float(existing.get("standby_power_kw", 0.0) or 0.0)
        control = str(existing.get("control") or DEFAULT_BATTERY_CONTROL).strip().lower()
        if control not in BATTERY_CONTROL_VALUES:
            control = DEFAULT_BATTERY_CONTROL
        kind = str(existing.get("kind") or DEFAULT_BATTERY_KIND).strip().lower()
        if kind not in _KIND_VALUES:
            kind = DEFAULT_BATTERY_KIND
        bat_type = str(existing.get("type") or "house").strip().lower() or "house"
        backing = str(existing.get("backing") or "virtual").strip().lower() or "virtual"
        role = str(existing.get("role") or "single_use").strip().lower() or "single_use"
        attached_ids = [
            str(cid).strip()
            for cid in (existing.get("attached_consumer_ids") or [])
            if str(cid or "").strip()
        ]
        if not attached_ids:
            singular = str(existing.get("attached_consumer_id") or "").strip()
            if singular:
                attached_ids = [singular]
        limits_from_live = bool(existing.get("limits_from_live", False))
        wear = existing.get("battery_wear") or {}
        wear_enabled = bool(wear.get("enabled", False))
        wear_replacement_cost = float(wear.get("replacement_cost_euro", 1500.0))
        wear_expected_cycles = float(wear.get("expected_cycles", 6000.0))
        wear_cycle_fraction = float(wear.get("cycle_cost_fraction", 0.5))
    else:
        label = allocate_unique_label("5 kWh Speicher", list_batteries())
        capacity = 5.0
        max_charge = 2.5
        max_discharge = 2.5
        efficiency = 0.97
        min_soc = 10.0
        max_soc = 100.0
        threshold_percent = 5.0
        standby_power = 0.0
        control = DEFAULT_BATTERY_CONTROL
        kind = DEFAULT_BATTERY_KIND
        bat_type = "house"
        backing = "virtual"
        role = "single_use"
        attached_ids = []
        limits_from_live = False
        wear_enabled = False
        wear_replacement_cost = 1500.0
        wear_expected_cycles = 6000.0
        wear_cycle_fraction = 0.5

    st.session_state[_scoped_key(session_scope, "planning_battery_label")] = label
    st.session_state[_scoped_key(session_scope, "planning_battery_type")] = (
        "Powerstation" if bat_type == "powerstation" else "Hausbatterie"
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_backing")] = (
        "Virtuell (Carve-out)" if backing == "virtual" else "Physisch"
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_role")] = (
        "Single-use (manuell)" if role == "single_use" else "Standby-Backup"
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_attached")] = (
        attached_ids[0] if attached_ids else ""
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_attached_ids")] = (
        list(attached_ids)
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_kind")] = KIND_LABELS_DE[
        kind
    ]
    st.session_state[_scoped_key(session_scope, "planning_battery_capacity")] = capacity
    st.session_state[_scoped_key(session_scope, "planning_battery_charge_power")] = (
        max_charge
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_discharge_power")] = (
        max_discharge
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_efficiency")] = efficiency
    st.session_state[_scoped_key(session_scope, "planning_battery_min_soc")] = min_soc
    st.session_state[_scoped_key(session_scope, "planning_battery_max_soc")] = max_soc
    st.session_state[_scoped_key(session_scope, "planning_battery_threshold")] = threshold_percent
    st.session_state[_scoped_key(session_scope, "planning_battery_standby")] = standby_power
    st.session_state[_scoped_key(session_scope, "planning_battery_control")] = (
        CONTROL_LABELS_DE[control]
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_limits_from_live")] = (
        limits_from_live
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_wear_enabled")] = wear_enabled
    st.session_state[
        _scoped_key(session_scope, "planning_battery_wear_replacement_cost")
    ] = wear_replacement_cost
    st.session_state[
        _scoped_key(session_scope, "planning_battery_wear_expected_cycles")
    ] = wear_expected_cycles
    st.session_state[
        _scoped_key(session_scope, "planning_battery_wear_cycle_fraction")
    ] = wear_cycle_fraction


def _battery_widget_state_missing(session_scope: str) -> bool:
    """True when sync metadata exists but scoped widget keys were dropped (e.g. page navigation)."""
    return _scoped_key(session_scope, "planning_battery_label") not in st.session_state


def _sync_battery_session(session_scope: str, existing: dict, *, file_stamp: str) -> None:
    scope_changed = st.session_state.get(_SESSION_SYNC_KEY) != session_scope
    file_changed = st.session_state.get(_SESSION_FILE_STAMP_KEY) != file_stamp
    widget_state_missing = _battery_widget_state_missing(session_scope)
    if scope_changed or file_changed or widget_state_missing:
        _clear_scoped_widget_keys(session_scope)
        _seed_battery_widget_state(session_scope, existing)
        st.session_state[_SESSION_SYNC_KEY] = session_scope
        st.session_state[_SESSION_FILE_STAMP_KEY] = file_stamp


def _apply_pending_battery_select() -> None:
    pending = st.session_state.pop(_SESSION_SELECT_PENDING_KEY, None)
    if pending is not None:
        st.session_state["planning_battery_select"] = pending


def _initial_battery_index(battery_ids: list[str]) -> int | None:
    if "planning_battery_select" in st.session_state:
        return None
    battery_id = str(get_live_scenario_refs().get("battery_id", "") or "").strip()
    if battery_id in battery_ids:
        return battery_ids.index(battery_id) + 1
    return None


def _battery_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in list_batteries()}


def _battery_selectbox(options: list[str], initial_index: int | None) -> str:
    if initial_index is not None:
        return labeled_selectbox(
            "Batterie",
            options=options,
            index=initial_index,
            key="planning_battery_select",
        )
    return labeled_selectbox(
        "Batterie",
        options=options,
        key="planning_battery_select",
    )


def _resolve_battery_existing(
    selected: str,
    battery_map: dict[str, dict],
    *,
    is_new: bool,
) -> dict:
    if is_new:
        source_id = str(st.session_state.get(_SESSION_TEMPLATE_SOURCE_KEY) or "")
        return new_battery_template(
            list_batteries(),
            source_id=source_id,
            live_battery_id=str(
                get_live_scenario_refs().get("battery_id", "") or ""
            ),
        )
    _remember_battery_template_source(selected)
    st.session_state[_SESSION_SELECTED_ID_KEY] = selected
    return battery_map.get(selected, {})


def _render_battery_select() -> dict:
    """Battery selectbox plus session reseed; returns the editor context."""
    _apply_pending_battery_select()
    battery_map = _battery_by_id()
    battery_ids = sorted(battery_map.keys())
    options, id_by_display = label_select_choices(battery_map, battery_ids)
    align_label_select_session(
        select_key="planning_battery_select",
        selected_id_key=_SESSION_SELECTED_ID_KEY,
        entity_map=battery_map,
        entity_ids=battery_ids,
        id_by_display=id_by_display,
    )
    initial_index = _initial_battery_index(battery_ids)
    selected_display = _battery_selectbox(options, initial_index)
    selected = resolve_label_select(selected_display, id_by_display)
    is_new = selected == NEW_OPTION
    existing = _resolve_battery_existing(selected, battery_map, is_new=is_new)
    session_scope = _battery_session_scope(selected, is_new=is_new)
    file_stamp = _config_file_stamp()
    _sync_battery_session(session_scope, existing, file_stamp=file_stamp)
    return {
        "battery_ids": battery_ids,
        "is_new": is_new,
        "existing": existing,
        "session_scope": session_scope,
    }


def _manual_consumer_options() -> tuple[list[str], dict[str, str]]:
    """Manual consumer ids from house profiles for Powerstation attachment."""
    from ui.house_config_io import load_house_profiles

    options: list[str] = [""]
    labels: dict[str, str] = {"": "— Verbraucher wählen —"}
    try:
        doc = load_house_profiles()
    except Exception:
        return options, labels
    # load_house_profiles_document normalizes profiles to dict[id → profile].
    raw_profiles = doc.get("profiles") or {}
    if isinstance(raw_profiles, dict):
        profile_iter = raw_profiles.values()
    elif isinstance(raw_profiles, list):
        profile_iter = raw_profiles
    else:
        profile_iter = []
    for profile in profile_iter:
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict):
                continue
            if str(consumer.get("earnie_role") or "").strip().lower() != "manual":
                continue
            cid = str(consumer.get("id") or "").strip()
            if not cid or cid in labels:
                continue
            options.append(cid)
            clabel = str(consumer.get("label") or cid).strip() or cid
            labels[cid] = f"{clabel} ({cid})"
    return options, labels


def _ensure_attached_options(
    options: list[str],
    labels: dict[str, str],
    current_ids: list[str],
) -> None:
    for cid in current_ids:
        if cid and cid not in options:
            options.append(cid)
            labels[cid] = f"{cid} (nicht in Hausprofil)"


def _render_attached_consumers(
    session_scope: str, *, backing: str
) -> list[str]:
    """Virtual: multi-select; physical: single consumer (one-way pack)."""
    attached_options, attached_labels = _manual_consumer_options()
    # Drop empty placeholder for multiselect; keep for single select.
    multi_options = [cid for cid in attached_options if cid]
    if backing == BACKING_VIRTUAL:
        current_ids = [
            str(cid).strip()
            for cid in (
                st.session_state.get(
                    _scoped_key(session_scope, "planning_battery_attached_ids"),
                    [],
                )
                or []
            )
            if str(cid or "").strip()
        ]
        _ensure_attached_options(multi_options, attached_labels, current_ids)
        # Session key seeded in _seed_battery_widget_state (no default= with key).
        selected = labeled_multiselect(
            "Angeschlossene Verbraucher",
            options=multi_options,
            format_func=lambda value: attached_labels.get(value, value or "—"),
            key=_scoped_key(session_scope, "planning_battery_attached_ids"),
            help="Virtuell: gemeinsame Energiereserve für mehrere manuelle Geräte.",
        )
        st.caption(
            "Powerstations nicht in Szenario-`battery_ids`. Mehrere Verbraucher "
            "teilen sich den Carve-out — oder Zuordnung unter Hausprofil → "
            "manuelles Gerät → Unterstützung „Energiereserve“."
        )
        return [str(cid).strip() for cid in (selected or []) if str(cid).strip()]

    current_attached = str(
        st.session_state.get(
            _scoped_key(session_scope, "planning_battery_attached"), ""
        )
        or ""
    ).strip()
    _ensure_attached_options(attached_options, attached_labels, [current_attached])
    index_default = (
        attached_options.index(current_attached)
        if current_attached in attached_options
        else 0
    )
    attached = labeled_selectbox(
        "Angeschlossener Verbraucher",
        options=attached_options,
        index=index_default,
        format_func=lambda value: attached_labels.get(value, value or "—"),
        key=_scoped_key(session_scope, "planning_battery_attached"),
        help="Physisch: ein Gerät pro One-Way-Pack.",
    )
    st.caption(
        "Powerstations nicht in Szenario-`battery_ids`. Verbraucher optional "
        "hier wählen — oder später unter Hausprofil → manuelles Gerät → "
        "Unterstützung „Energiereserve“ die Powerstation zuordnen "
        "(verknüpft automatisch)."
    )
    cid = str(attached or "").strip()
    return [cid] if cid else []


def _render_powerstation_meta(session_scope: str) -> tuple[str, str, list[str]]:
    """Backing / role / attached consumers. Returns (backing, role, ids)."""
    backing_label = labeled_selectbox(
        "Backing",
        options=["Virtuell (Carve-out)", "Physisch"],
        key=_scoped_key(session_scope, "planning_battery_backing"),
    )
    backing = "physical" if backing_label == "Physisch" else BACKING_VIRTUAL
    role_label = labeled_selectbox(
        "Rolle",
        options=["Single-use (manuell)", "Standby-Backup"],
        key=_scoped_key(session_scope, "planning_battery_role"),
    )
    role = "standby_backup" if role_label == "Standby-Backup" else "single_use"
    attached_ids = _render_attached_consumers(session_scope, backing=backing)
    return backing, role, attached_ids


def _render_battery_power_efficiency(
    session_scope: str, *, bat_type: str
) -> tuple[float, float, float]:
    max_charge = labeled_number_input(
        "Max. Ladeleistung (kW)",
        min_value=0.1,
        step=0.1,
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, "planning_battery_charge_power"),
    )
    discharge_kwargs: dict = {
        "min_value": 0.0 if bat_type == "powerstation" else 0.1,
        "step": 0.1,
        "ratios": WIDE_LABEL_RATIOS,
        "key": _scoped_key(session_scope, "planning_battery_discharge_power"),
    }
    if bat_type == "powerstation":
        discharge_kwargs["help"] = (
            "Bei physischer Powerstation 0 = kein Hausnetz-Rückspeisen."
        )
    max_discharge = labeled_number_input(
        "Max. Entladeleistung (kW)",
        **discharge_kwargs,
    )
    efficiency = labeled_number_input(
        "Wirkungsgrad",
        min_value=0.5,
        max_value=1.0,
        step=0.01,
        key=_scoped_key(session_scope, "planning_battery_efficiency"),
    )
    return max_charge, max_discharge, efficiency


def _virtual_ps_inherited_ui_fields(
    *,
    capacity: float,
    exclude_id: str = "",
) -> tuple[dict, dict | None]:
    """Map inherited JSON fields onto form keys; return (fields, primary_house)."""
    primary = primary_house_battery(list_batteries(), exclude_id=exclude_id)
    fill = virtual_powerstation_fill_fields(
        primary_house=primary,
        capacity_kwh=float(capacity or 0.0),
    )
    fields = {
        "max_charge": float(fill["battery_max_charge_power_kw"]),
        "max_discharge": float(fill["battery_max_discharge_power_kw"]),
        "efficiency": float(fill["battery_efficiency"]),
        "limits_from_live": bool(fill["limits_from_live"]),
        "min_soc": float(fill["battery_min_soc"]),
        "max_soc": float(fill["battery_max_soc"]),
        "threshold_percent": float(fill["threshold_power"]) * 100.0,
        "standby_power": float(fill["standby_power_kw"]),
        "kind": fill["kind"],
        "control": fill["control"],
        "battery_wear": dict(fill["battery_wear"]),
    }
    return fields, primary


def _render_battery_core_fields(session_scope: str) -> dict:
    label = labeled_text_input(
        "Bezeichnung",
        key=_scoped_key(session_scope, "planning_battery_label"),
    )
    type_label = labeled_selectbox(
        "Typ",
        options=["Hausbatterie", "Powerstation"],
        key=_scoped_key(session_scope, "planning_battery_type"),
    )
    bat_type = "powerstation" if type_label == "Powerstation" else "house"
    backing = BACKING_VIRTUAL
    role = "single_use"
    attached_ids: list[str] = []
    if bat_type == "powerstation":
        backing, role, attached_ids = _render_powerstation_meta(session_scope)
    is_virtual_ps = bat_type == "powerstation" and backing == BACKING_VIRTUAL
    capacity_kwargs: dict = {
        "min_value": 0.1,
        "step": 0.5,
        "key": _scoped_key(session_scope, "planning_battery_capacity"),
    }
    if is_virtual_ps:
        capacity_kwargs["help"] = "Max. Reserve / Carve-out auf der Hausbatterie."
    capacity = labeled_number_input("Kapazität (kWh)", **capacity_kwargs)
    attached_fields = {
        "attached_consumer_ids": list(attached_ids),
        "attached_consumer_id": attached_ids[0] if attached_ids else "",
    }
    if is_virtual_ps:
        return {
            "label": label,
            "type": bat_type,
            "backing": backing,
            "role": role,
            **attached_fields,
            "capacity": capacity,
            "is_virtual_ps": True,
        }
    max_charge, max_discharge, efficiency = _render_battery_power_efficiency(
        session_scope, bat_type=bat_type
    )
    return {
        "label": label,
        "type": bat_type,
        "backing": backing,
        "role": role,
        **attached_fields,
        "capacity": capacity,
        "max_charge": max_charge,
        "max_discharge": max_discharge,
        "efficiency": efficiency,
        "is_virtual_ps": False,
    }


def _render_battery_limit_fields(session_scope: str) -> dict:
    limits_from_live = labeled_checkbox(
        "Grenzwerte im Live-Betrieb vom Wechselrichter / Speicher übernehmen",
        help="SOC-Min/Max und Max. Lade-/Entladeleistung aus EHAL-Telemetrie "
        "(get_ess_*); sonst Hauskonfigurator. Fehlendes Mapping → HK-Fallback.",
        key=_scoped_key(session_scope, "planning_battery_limits_from_live"),
    )
    min_soc = labeled_number_input(
        "Minimaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        key=_scoped_key(session_scope, "planning_battery_min_soc"),
    )
    max_soc = labeled_number_input(
        "Maximaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        key=_scoped_key(session_scope, "planning_battery_max_soc"),
    )
    threshold_percent = labeled_number_input(
        "Leistungs-Schwelle (%)",
        min_value=1.0,
        max_value=100.0,
        help="Anteil der größeren von Max. Lade-/Entladeleistung.",
        key=_scoped_key(session_scope, "planning_battery_threshold"),
    )
    standby_power = labeled_number_input(
        "Standby-Leistung (kW)",
        min_value=0.0,
        step=0.01,
        help="Dauerhafte AC-Eigenleistung der Batterie (24/7 Verbrauch).",
        key=_scoped_key(session_scope, "planning_battery_standby"),
    )
    kind_labels = [KIND_LABELS_DE[v] for v in _KIND_VALUES]
    kind_label = labeled_selectbox(
        "Topologie",
        options=kind_labels,
        help="Batterie+WR: Automatik/Optimieren erlaubt. "
        "Isolierte Batterie: nur Laden / Entladen / Standby (nie Automatik).",
        key=_scoped_key(session_scope, "planning_battery_kind"),
    )
    label_to_kind = {v: k for k, v in KIND_LABELS_DE.items()}
    kind = label_to_kind.get(str(kind_label), DEFAULT_BATTERY_KIND)
    control_labels = [CONTROL_LABELS_DE[v] for v in sorted(BATTERY_CONTROL_VALUES)]
    control_label = labeled_selectbox(
        "Steuerbarkeit",
        options=control_labels,
        help="full = Zwangsladen/-entladen; limits_only = nur Grenzen; "
        "read_only = Eigenverbrauch ohne Setpoints.",
        key=_scoped_key(session_scope, "planning_battery_control"),
    )
    label_to_control = {v: k for k, v in CONTROL_LABELS_DE.items()}
    control = label_to_control.get(str(control_label), DEFAULT_BATTERY_CONTROL)
    return {
        "limits_from_live": limits_from_live,
        "min_soc": min_soc,
        "max_soc": max_soc,
        "threshold_percent": threshold_percent,
        "standby_power": standby_power,
        "kind": kind,
        "control": control,
    }


def _render_battery_wear_fields(session_scope: str) -> dict:
    wear_enabled = labeled_checkbox(
        "Verschleiß berücksichtigen",
        key=_scoped_key(session_scope, "planning_battery_wear_enabled"),
    )
    if not wear_enabled:
        return {"enabled": False}
    wear_replacement_cost = labeled_number_input(
        "Ersatzkosten (€)",
        min_value=0.01,
        step=50.0,
        key=_scoped_key(session_scope, "planning_battery_wear_replacement_cost"),
    )
    wear_expected_cycles = labeled_number_input(
        "Erwartete Vollzyklen",
        min_value=1.0,
        step=100.0,
        key=_scoped_key(session_scope, "planning_battery_wear_expected_cycles"),
    )
    wear_cycle_fraction = labeled_number_input(
        "Anteil zyklenbedingter Kosten",
        min_value=0.01,
        max_value=1.0,
        step=0.05,
        help="Rest wird als Kalenderalterung angenommen (nicht separat modelliert).",
        key=_scoped_key(session_scope, "planning_battery_wear_cycle_fraction"),
    )
    return {
        "enabled": True,
        "replacement_cost_euro": wear_replacement_cost,
        "expected_cycles": wear_expected_cycles,
        "cycle_cost_fraction": wear_cycle_fraction,
    }


def _render_battery_fields(session_scope: str, *, exclude_id: str = "") -> dict:
    fields = _render_battery_core_fields(session_scope)
    if fields.get("is_virtual_ps"):
        inherited, primary = _virtual_ps_inherited_ui_fields(
            capacity=float(fields.get("capacity") or 0.0),
            exclude_id=exclude_id,
        )
        fields.update(inherited)
        if primary is None:
            st.warning(
                "Virtuelle Powerstation braucht eine Hausbatterie als "
                "Carve-out-Basis. Fehlende Werte werden mit Standardwerten "
                "gefüllt."
            )
        else:
            house_label = str(
                primary.get("label") or primary.get("id") or "Hausbatterie"
            ).strip()
            st.caption(
                f"Lade-/Entladeleistung, Wirkungsgrad, SoC und Grenzen werden "
                f"von der Hausbatterie „{house_label}“ übernommen "
                f"(Carve-out, keine eigene Hardware)."
            )
        return fields
    fields.update(_render_battery_limit_fields(session_scope))
    fields["battery_wear"] = _render_battery_wear_fields(session_scope)
    return fields


def _battery_save_payload(fields: dict) -> dict:
    payload = {
        "label": fields["label"],
        "type": fields.get("type") or "house",
        "kind": fields.get("kind") or DEFAULT_BATTERY_KIND,
        "battery_capacity_kwh": fields["capacity"],
        "battery_max_charge_power_kw": fields["max_charge"],
        "battery_max_discharge_power_kw": fields["max_discharge"],
        "battery_efficiency": fields["efficiency"],
        "battery_min_soc": fields["min_soc"],
        "battery_max_soc": fields["max_soc"],
        "threshold_power": fields["threshold_percent"] / 100.0,
        "standby_power_kw": float(fields["standby_power"] or 0.0),
        "control": fields.get("control") or DEFAULT_BATTERY_CONTROL,
        "limits_from_live": bool(fields.get("limits_from_live", False)),
        "ehal_bindings": dict(fields.get("ehal_bindings") or {}),
        "battery_wear": fields["battery_wear"],
    }
    if payload["type"] == "powerstation":
        payload["backing"] = fields.get("backing") or "virtual"
        payload["role"] = fields.get("role") or "single_use"
        attached_ids = [
            str(cid).strip()
            for cid in (fields.get("attached_consumer_ids") or [])
            if str(cid or "").strip()
        ]
        if not attached_ids:
            singular = str(fields.get("attached_consumer_id") or "").strip()
            if singular:
                attached_ids = [singular]
        payload["attached_consumer_ids"] = attached_ids
        payload["attached_consumer_id"] = attached_ids[0] if attached_ids else ""
    return payload


def _save_battery(
    fields: dict,
    *,
    stable_id: str,
    entity_id: str,
    is_new: bool,
) -> None:
    try:
        upsert_battery(_battery_save_payload(fields), stable_id=stable_id)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
    if is_new:
        st.session_state[_SESSION_SELECT_PENDING_KEY] = entity_id
        st.session_state[_SESSION_SYNC_KEY] = None
        st.rerun()


def _persist_battery_form(
    fields: dict,
    *,
    stable_id: str,
    entity_id: str,
    is_new: bool,
    ready: bool,
) -> None:
    payload = {"id": entity_id, **_battery_save_payload(fields)}
    persist_key = f"planning_battery::{entity_id}"
    suppress = bool(st.session_state.pop(_SESSION_SUPPRESS_AUTOPERSIST_KEY, False))
    if suppress and ready:
        # Mark draft as clean without writing so delete-of-last is not undone.
        st.session_state[f"_auto_persist_fp::{persist_key}"] = payload_fingerprint(
            payload
        )
        wrote = False
    else:
        wrote = auto_persist(
            state_key=persist_key,
            payload=payload,
            save=lambda: _save_battery(
                fields,
                stable_id=stable_id,
                entity_id=entity_id,
                is_new=is_new,
            ),
            ready=ready,
        )
    if wrote:
        st.rerun()


def _render_battery_delete(stable_id: str) -> None:
    if not st.button("Batterie entfernen", key="planning_battery_delete"):
        return
    try:
        delete_battery(stable_id)
    except ValueError as exc:
        st.error(str(exc))
        return
    remaining_ids = sorted(_battery_by_id().keys())
    fallback = remaining_ids[0] if remaining_ids else NEW_OPTION
    _clear_scoped_widget_keys(stable_id)
    _clear_scoped_widget_keys("__new__")
    st.session_state.pop(_SESSION_SELECTED_ID_KEY, None)
    st.session_state.pop(f"_auto_persist_fp::planning_battery::{stable_id}", None)
    st.session_state[_SESSION_SELECT_PENDING_KEY] = fallback
    st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
    st.session_state[_SESSION_SYNC_KEY] = None
    if fallback == NEW_OPTION:
        st.session_state[_SESSION_SUPPRESS_AUTOPERSIST_KEY] = True
    st.success("Batterie entfernt.")
    st.rerun()


def render_battery_planning_tab() -> None:
    st.caption(
        "Nicht optional, da ansonsten identisch mit Nicht optimierter Referenz."
    )
    ctx = _render_battery_select()
    is_new = ctx["is_new"]
    stable_id = "" if is_new else str(ctx["existing"].get("id", ""))
    fields = _render_battery_fields(ctx["session_scope"], exclude_id=stable_id)
    label = fields["label"]
    ready = bool(str(label or "").strip()) and float(fields["capacity"] or 0) > 0
    taken = {bid for bid in ctx["battery_ids"] if bid != stable_id}
    entity_id = stable_id.strip() or slug_id(label or "batterie", existing=taken)
    _persist_battery_form(
        fields,
        stable_id=stable_id,
        entity_id=entity_id,
        is_new=is_new,
        ready=ready,
    )
    if not is_new and stable_id:
        _render_battery_delete(stable_id)
