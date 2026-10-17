"""Battery tab session state: scoped widget keys, disk reseed, new-battery template.

Split out of ``ui.planning_battery_form`` (names stay importable from there).
"""
from __future__ import annotations

import copy
import os

import streamlit as st

from house_config.battery_control import (
    BATTERY_CONTROL_VALUES,
    CONTROL_LABELS_DE,
    DEFAULT_BATTERY_CONTROL,
)
from house_config.entity_id_lock import ID_PROVISIONAL_LABEL_KEY, is_id_locked
from house_config.label_uniqueness import allocate_unique_label
from house_config.topology_regulates import REGULATES_ON_GRID, REGULATES_ON_NONE
from runtime_store.persist_paths import resolve_config_json_path
from ui.house_config_io import list_batteries
from ui.label_select import NEW_OPTION
from ui.planning_battery_inverter import (
    default_inverter_id_for_new_house,
    owned_inverter_for_battery,
    seed_builtin_inverter_widgets,
)

_SESSION_SYNC_KEY = "planning_battery_sync_id"
_SESSION_FILE_STAMP_KEY = "planning_battery_file_stamp"
_SESSION_SELECT_PENDING_KEY = "planning_battery_select_pending"
_SESSION_SELECTED_ID_KEY = "planning_battery_selected_id"
_SESSION_SUPPRESS_AUTOPERSIST_KEY = "planning_battery_suppress_autopersist"
_SESSION_TEMPLATE_SOURCE_KEY = "planning_battery_template_source"
_SESSION_PROVISIONAL_LABEL_KEY = "planning_battery_provisional_label"


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
    # New drafts are always Hausbatterie (no type). Powerstations may be
    # charge-only (discharge 0); house rules require both 0 or both > 0.
    if bool(charge_kw) != bool(discharge_kw):
        both = charge_kw or discharge_kw
        charge_kw = both
        discharge_kw = both
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
        "control": str(source.get("control") or "full").strip().lower() or "full",
        "regulates_on": str(source.get("regulates_on") or REGULATES_ON_GRID)
        .strip()
        .lower()
        or REGULATES_ON_GRID,
        "limits_from_live": bool(source.get("limits_from_live", False)),
        "inverter_id": str(source.get("inverter_id") or "").strip()
        or default_inverter_id_for_new_house(),
        # New id/slug — never copy entity-scoped bindings from the source battery.
        "ehal_bindings": {},
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


def _battery_seed_from_existing(existing: dict) -> dict:
    """Widget seed values of a stored battery entry."""
    from house_config.entity_resolution import split_battery_max_power_kw

    max_charge, max_discharge = split_battery_max_power_kw(existing)
    control = str(existing.get("control") or DEFAULT_BATTERY_CONTROL).strip().lower()
    if control not in BATTERY_CONTROL_VALUES:
        control = DEFAULT_BATTERY_CONTROL
    regulates_on = str(
        existing.get("regulates_on") or REGULATES_ON_GRID
    ).strip().lower()
    if regulates_on not in (REGULATES_ON_GRID, REGULATES_ON_NONE):
        regulates_on = REGULATES_ON_GRID
    attached_ids = [
        str(cid).strip()
        for cid in (existing.get("attached_consumer_ids") or [])
        if str(cid or "").strip()
    ]
    if not attached_ids:
        singular = str(existing.get("attached_consumer_id") or "").strip()
        if singular:
            attached_ids = [singular]
    wear = existing.get("battery_wear") or {}
    return {
        "label": str(existing.get("label", "5 kWh Speicher")),
        "capacity": float(existing.get("battery_capacity_kwh", 5.0)),
        "max_charge": max_charge,
        "max_discharge": max_discharge,
        "efficiency": float(existing.get("battery_efficiency", 0.97)),
        "min_soc": float(existing.get("battery_min_soc", 10.0)),
        "max_soc": float(existing.get("battery_max_soc", 100.0)),
        "threshold_percent": float(existing.get("threshold_power", 0.05)) * 100.0,
        "standby_power": float(existing.get("standby_power_kw", 0.0) or 0.0),
        "control": control,
        "regulates_on": regulates_on,
        "bat_type": str(existing.get("type") or "house").strip().lower() or "house",
        "backing": str(existing.get("backing") or "virtual").strip().lower() or "virtual",
        "role": str(existing.get("role") or "single_use").strip().lower() or "single_use",
        "attached_ids": attached_ids,
        "limits_from_live": bool(existing.get("limits_from_live", False)),
        "inverter_id": str(existing.get("inverter_id") or "").strip(),
        "wear_enabled": bool(wear.get("enabled", False)),
        "wear_replacement_cost": float(wear.get("replacement_cost_euro", 1500.0)),
        "wear_expected_cycles": float(wear.get("expected_cycles", 6000.0)),
        "wear_cycle_fraction": float(wear.get("cycle_cost_fraction", 0.5)),
    }


def _battery_seed_defaults() -> dict:
    """Widget seed values of a new battery."""
    return {
        "label": allocate_unique_label("5 kWh Speicher", list_batteries()),
        "capacity": 5.0,
        "max_charge": 2.5,
        "max_discharge": 2.5,
        "efficiency": 0.97,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "threshold_percent": 5.0,
        "standby_power": 0.0,
        "control": DEFAULT_BATTERY_CONTROL,
        "regulates_on": REGULATES_ON_GRID,
        "bat_type": "house",
        "backing": "virtual",
        "role": "single_use",
        "attached_ids": [],
        "limits_from_live": False,
        "inverter_id": default_inverter_id_for_new_house(),
        "wear_enabled": False,
        "wear_replacement_cost": 1500.0,
        "wear_expected_cycles": 6000.0,
        "wear_cycle_fraction": 0.5,
    }


# (widget key suffix, seed value key) for values written 1:1 into the session.
_BATTERY_DIRECT_WIDGETS = (
    ("planning_battery_capacity", "capacity"),
    ("planning_battery_charge_power", "max_charge"),
    ("planning_battery_discharge_power", "max_discharge"),
    ("planning_battery_efficiency", "efficiency"),
    ("planning_battery_min_soc", "min_soc"),
    ("planning_battery_max_soc", "max_soc"),
    ("planning_battery_threshold", "threshold_percent"),
    ("planning_battery_standby", "standby_power"),
    ("planning_battery_limits_from_live", "limits_from_live"),
    ("planning_battery_wear_enabled", "wear_enabled"),
    ("planning_battery_wear_replacement_cost", "wear_replacement_cost"),
    ("planning_battery_wear_expected_cycles", "wear_expected_cycles"),
    ("planning_battery_wear_cycle_fraction", "wear_cycle_fraction"),
)

_REGULATES_LABELS = {
    REGULATES_ON_GRID: "Netz-Zähler (Eigenverbrauch / Zero-Export)",
    REGULATES_ON_NONE: "Keiner (nur Setpoints)",
}


def _seed_battery_label_state(session_scope: str, existing: dict, label: str) -> None:
    st.session_state[_scoped_key(session_scope, "planning_battery_label")] = label
    # Seed Bezeichnung for deferred id lock (new / unlocked entities).
    if session_scope == "__new__" or (existing and not is_id_locked(existing)):
        if existing:
            seed = str(existing.get(ID_PROVISIONAL_LABEL_KEY) or label).strip()
        else:
            seed = str(label).strip()
        st.session_state[_SESSION_PROVISIONAL_LABEL_KEY] = seed


def _seed_battery_widget_state(session_scope: str, existing: dict) -> None:
    values = _battery_seed_from_existing(existing) if existing else _battery_seed_defaults()
    _seed_battery_label_state(session_scope, existing, values["label"])
    st.session_state[_scoped_key(session_scope, "planning_battery_type")] = (
        "Powerstation" if values["bat_type"] == "powerstation" else "Hausbatterie"
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_backing")] = (
        "Virtuell (Carve-out)" if values["backing"] == "virtual" else "Physisch"
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_role")] = (
        "Single-use (manuell)" if values["role"] == "single_use" else "Standby-Backup"
    )
    attached_ids = values["attached_ids"]
    st.session_state[_scoped_key(session_scope, "planning_battery_attached")] = (
        attached_ids[0] if attached_ids else ""
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_attached_ids")] = (
        list(attached_ids)
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_inverter_id")] = (
        values["inverter_id"]
    )
    bat_id = str(existing.get("id") or "").strip()
    seed_builtin_inverter_widgets(session_scope, owned_inverter_for_battery(bat_id))
    for suffix, value_key in _BATTERY_DIRECT_WIDGETS:
        st.session_state[_scoped_key(session_scope, suffix)] = values[value_key]
    st.session_state[_scoped_key(session_scope, "planning_battery_control")] = (
        CONTROL_LABELS_DE[values["control"]]
    )
    st.session_state[_scoped_key(session_scope, "planning_battery_regulates_on")] = (
        _REGULATES_LABELS.get(values["regulates_on"], _REGULATES_LABELS[REGULATES_ON_GRID])
    )


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
