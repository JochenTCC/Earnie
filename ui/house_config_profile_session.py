"""Session/select/defaults for Hausprofil form."""
from __future__ import annotations

import os

import streamlit as st

from house_config.earnie_role import (
    DEFAULT_MANUAL_HORIZON_H,
    EARNIE_ROLE_FLEX,
    EARNIE_ROLE_KNOWN,
    EARNIE_ROLE_MANUAL,
    resolve_earnie_role,
)
from house_config.generic_schedule import (
    DEFAULT_START_HOUR,
    MAX_START_SHIFT_H,
    format_start_window_caption,
    generic_annual_kwh,
    reject_legacy_start_flexibility,
)
from house_config.id_slug import slug_id
from house_config.thermal_labels import (
    CONSUMER_TYPE_LABELS,
    building_class_option_label,
)
from runtime_store.persist_paths import resolve_house_profiles_json_path
from ui.house_config_io import (
    apply_csv_path_pending,
    csv_upload_widget_key,
    load_house_profiles,
    preview_baseload,
    queue_csv_path_update,
    save_profile_consumption_csv,
    single_csv_upload,
    upsert_house_profile,
)
from ui.auto_persist import auto_persist
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
    labeled_checkbox,
    labeled_number_input,
    labeled_selectbox,
    labeled_text_input,
)


_PASSTHROUGH_CONSUMER_KEYS = (
    "loxone_inputs",
    "loxone_outputs",
    "optimizer_flex",
    "thermal_flex_window",
    "max_on_quarterhours",
    "max_pulses_per_day",
    "min_on_quarterhours",
    "heating_power_threshold_kw",
    "actual_temp_step_c",
    "thermal_control",
    "filter_schedule",
    "daily_target_source",
    "daily_target_kwh",
    "profile_csv",
    "use_profile_csv",
    "ehal_bindings",
)

_EARNIE_ROLE_LABELS = {
    EARNIE_ROLE_KNOWN: "Bekannt (Grundlast)",
    EARNIE_ROLE_FLEX: "Gesteuert (Optimierung)",
    EARNIE_ROLE_MANUAL: "Manuelles Gerät",
}
_EARNIE_ROLE_OPTIONS = [EARNIE_ROLE_KNOWN, EARNIE_ROLE_FLEX, EARNIE_ROLE_MANUAL]



CONSUMER_TYPE_OPTIONS = ["generic", "thermal_annual", "thermal_rc", "ev"]

_SESSION_SYNC_KEY = "house_profile_sync_id"

_SESSION_CONSUMERS_KEY = "house_profile_consumers"

_SESSION_SELECT_PENDING_KEY = "house_profile_select_pending"

_SESSION_SELECTED_ID_KEY = "house_profile_selected_id"

_NEW_PROFILE_OPTION = "— neu —"

_SESSION_FILE_STAMP_KEY = "house_profile_file_stamp"

def _scoped_key(session_scope: str, base: str) -> str:
    return f"{session_scope}__{base}"

def _default_consumer() -> dict:
    return {
        "label": "Haus Wärme",
        "type": "thermal_annual",
        "nominal_power_kw": 3.5,
        "living_area_m2": 120.0,
        "building_class": 3,
        "heat_pump_type": "luft",
        "persons": 2,
    }

def _default_additional_consumer() -> dict:
    from house_config.label_uniqueness import allocate_unique_label

    existing = list(st.session_state.get(_SESSION_CONSUMERS_KEY, []))
    return {
        "label": allocate_unique_label("Verbraucher", existing),
        "type": "generic",
        "nominal_power_kw": 1.0,
        "schedule": {
            "runs_per_week": 0,
        },
    }

def _live_markers_enabled() -> bool:
    """True when Live UI mode is on (legacy; Merker editors moved to EHAL-Com)."""
    from ui.mode_selector import get_enabled_ui_mode_keys

    return "live_environment" in get_enabled_ui_mode_keys()

def _flatten_consumer_for_edit(consumer: dict) -> dict:
    item = dict(consumer)
    thermal = item.pop("thermal", None)
    if isinstance(thermal, dict):
        for key, value in thermal.items():
            if key not in item and key not in {"latitude", "longitude"}:
                item[key] = value
    return item

def _consumers_from_existing(existing: dict) -> list[dict]:
    consumers = list(existing.get("consumers", []))
    if not consumers:
        return []
    return [_flatten_consumer_for_edit(consumer) for consumer in consumers]

def _profile_session_scope(selected_id: str, *, is_new: bool) -> str:
    return "__new__" if is_new else selected_id

def _house_profiles_file_stamp() -> str:
    path = resolve_house_profiles_json_path()
    try:
        return f"{os.path.abspath(path)}:{os.path.getmtime(path)}"
    except OSError:
        return os.path.abspath(path)

def _clear_scoped_widget_keys(session_scope: str) -> None:
    prefix = f"{session_scope}__"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            del st.session_state[key]

def _clear_consumer_widget_keys(session_scope: str) -> None:
    """Drop index-scoped consumer widgets so remove does not leave stale labels."""
    prefix = f"{session_scope}__hc_"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            del st.session_state[key]

def _seed_profile_widget_state(
    session_scope: str,
    existing: dict,
    *,
    siblings: list[dict] | None = None,
) -> None:
    from house_config.label_uniqueness import allocate_unique_label

    if existing:
        label = str(existing.get("label", "Mein Haushalt"))
        annual_kwh = float(existing.get("annual_kwh", 4500.0))
        land = str(existing.get("land") or "AT").strip().upper()
        if land not in {"AT", "DE", "CH"}:
            land = "AT"
        latitude = float(existing.get("latitude", 48.2))
        longitude = float(existing.get("longitude", 11.0))
        default_pv_tilt = int(existing.get("default_pv_tilt", 25))
        default_pv_azimuth = int(existing.get("default_pv_azimuth", 0))
        nne_ap = float(existing.get("netznutzung_arbeitspreis_cent_kwh", 0.0) or 0.0)
    else:
        label = allocate_unique_label("Mein Haushalt", siblings or [])
        annual_kwh = 4500.0
        land = "AT"
        latitude = 48.2
        longitude = 11.0
        default_pv_tilt = 25
        default_pv_azimuth = 0
        nne_ap = 0.0
    st.session_state[_scoped_key(session_scope, "house_profile_label")] = label
    st.session_state[_scoped_key(session_scope, "house_annual_kwh")] = annual_kwh
    st.session_state[_scoped_key(session_scope, "house_profile_land")] = land
    st.session_state[_scoped_key(session_scope, "house_profile_latitude")] = latitude
    st.session_state[_scoped_key(session_scope, "house_profile_longitude")] = longitude
    st.session_state[_scoped_key(session_scope, "house_profile_default_pv_tilt")] = default_pv_tilt
    st.session_state[_scoped_key(session_scope, "house_profile_default_pv_azimuth")] = default_pv_azimuth
    st.session_state[_scoped_key(session_scope, "house_profile_nne_ap")] = nne_ap

def _profile_widget_state_missing(session_scope: str) -> bool:
    """True when sync metadata exists but scoped widget keys were dropped (e.g. page navigation)."""
    return _scoped_key(session_scope, "house_profile_label") not in st.session_state

def _sync_profile_session(
    session_scope: str,
    existing: dict,
    *,
    file_stamp: str,
    siblings: list[dict] | None = None,
) -> list[dict]:
    scope_changed = st.session_state.get(_SESSION_SYNC_KEY) != session_scope
    file_changed = st.session_state.get(_SESSION_FILE_STAMP_KEY) != file_stamp
    widget_state_missing = _profile_widget_state_missing(session_scope)
    if scope_changed or file_changed or widget_state_missing:
        _clear_scoped_widget_keys(session_scope)
        _seed_profile_widget_state(session_scope, existing, siblings=siblings)
        st.session_state[_SESSION_SYNC_KEY] = session_scope
        st.session_state[_SESSION_FILE_STAMP_KEY] = file_stamp
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(existing)
    return list(st.session_state.get(_SESSION_CONSUMERS_KEY, []))

def _resolve_profile_id(
    *,
    is_new: bool,
    existing_id: str,
    label: str,
    profile_ids: set[str],
) -> str:
    if not is_new and existing_id:
        return existing_id
    others = set(profile_ids)
    return slug_id(label, existing=others)

def _consumer_type_options(consumer_index: int) -> list[str]:
    if consumer_index == 0:
        return list(CONSUMER_TYPE_OPTIONS)
    return [value for value in CONSUMER_TYPE_OPTIONS if value != "thermal_annual"]

def _type_index(consumer_type: str, options: list[str]) -> int:
    try:
        return options.index(consumer_type)
    except ValueError:
        return 0

def _profile_display_label(profile_map: dict, profile_id: str) -> str:
    return str(profile_map.get(profile_id, {}).get("label") or profile_id)

def _profile_select_choices(
    profile_map: dict, profile_ids: list[str]
) -> tuple[list[str], dict[str, str]]:
    """Build selectbox options from live labels (not format_func) so UI refreshes."""
    displays = [_NEW_PROFILE_OPTION]
    id_by_display = {_NEW_PROFILE_OPTION: _NEW_PROFILE_OPTION}
    for profile_id in profile_ids:
        display = _profile_display_label(profile_map, profile_id)
        if display in id_by_display:
            display = f"{display} ({profile_id})"
        displays.append(display)
        id_by_display[display] = profile_id
    return displays, id_by_display

def _align_profile_select_session(
    profile_map: dict,
    profile_ids: list[str],
    id_by_display: dict[str, str],
) -> None:
    """Rewrite selectbox session value when Bezeichnung/labels change on disk."""
    current = st.session_state.get("house_profile_select")
    if current is not None and str(current) in id_by_display:
        mapped = id_by_display[str(current)]
        if mapped != _NEW_PROFILE_OPTION:
            st.session_state[_SESSION_SELECTED_ID_KEY] = mapped
        return

    selected_id = st.session_state.get(_SESSION_SELECTED_ID_KEY)
    if selected_id in profile_ids:
        st.session_state["house_profile_select"] = _profile_display_label(
            profile_map, str(selected_id)
        )
        return
    if current is not None and str(current) in profile_ids:
        st.session_state[_SESSION_SELECTED_ID_KEY] = str(current)
        st.session_state["house_profile_select"] = _profile_display_label(
            profile_map, str(current)
        )


def _profile_select_fallback_after_delete(
    profile_ids: list[str], deleted_id: str
) -> str:
    remaining = [pid for pid in profile_ids if pid != deleted_id]
    if remaining:
        return remaining[0]
    return _NEW_PROFILE_OPTION

def _default_existing_profile_id(profile_ids: list[str]) -> str:
    """Prefer Live-Szenario id, then greenfield ``live``, then first profile."""
    if not profile_ids:
        return ""
    from ui.house_config_io import get_runtime_scenario_refs

    profile_id = str(get_runtime_scenario_refs().get("house_profile_id", "") or "").strip()
    if profile_id in profile_ids:
        return profile_id
    if "live" in profile_ids:
        return "live"
    return profile_ids[0]


def _apply_pending_profile_select() -> None:
    pending = st.session_state.pop(_SESSION_SELECT_PENDING_KEY, None)
    if pending is not None:
        st.session_state["house_profile_select"] = pending

def _initial_profile_index(profile_ids: list[str]) -> int | None:
    if "house_profile_select" in st.session_state:
        return None
    selected = _default_existing_profile_id(profile_ids)
    if not selected:
        return None
    return profile_ids.index(selected) + 1
