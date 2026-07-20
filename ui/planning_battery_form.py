"""Batterie-Tab im Hauskonfigurator."""
from __future__ import annotations

import os

import streamlit as st

from house_config.id_slug import slug_id
from runtime_store.persist_paths import resolve_config_json_path
from ui.house_config_io import get_runtime_scenario_refs, list_batteries, upsert_battery
from ui.auto_persist import auto_persist
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
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
    from house_config.label_uniqueness import allocate_unique_label

    if existing:
        label = str(existing.get("label", "5 kWh Speicher"))
        capacity = float(existing.get("battery_capacity_kwh", 5.0))
        max_power = float(existing.get("battery_max_power_kw", 2.5))
        efficiency = float(existing.get("battery_efficiency", 0.97))
        min_soc = float(existing.get("battery_min_soc", 10.0))
        max_soc = float(existing.get("battery_max_soc", 100.0))
        threshold_percent = float(existing.get("threshold_power", 0.05)) * 100.0
    else:
        label = allocate_unique_label("5 kWh Speicher", list_batteries())
        capacity = 5.0
        max_power = 2.5
        efficiency = 0.97
        min_soc = 10.0
        max_soc = 100.0
        threshold_percent = 5.0

    st.session_state[_scoped_key(session_scope, "planning_battery_label")] = label
    st.session_state[_scoped_key(session_scope, "planning_battery_capacity")] = capacity
    st.session_state[_scoped_key(session_scope, "planning_battery_power")] = max_power
    st.session_state[_scoped_key(session_scope, "planning_battery_efficiency")] = efficiency
    st.session_state[_scoped_key(session_scope, "planning_battery_min_soc")] = min_soc
    st.session_state[_scoped_key(session_scope, "planning_battery_max_soc")] = max_soc
    st.session_state[_scoped_key(session_scope, "planning_battery_threshold")] = threshold_percent


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
    battery_id = str(get_runtime_scenario_refs().get("battery_id", "") or "").strip()
    if battery_id in battery_ids:
        return battery_ids.index(battery_id) + 1
    return None


def _battery_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in list_batteries()}


def render_battery_planning_tab() -> None:
    st.caption(
        "Nicht optional, da ansonsten identisch mit Nicht optimierter Referenz."
    )
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

    if initial_index is not None:
        selected_display = labeled_selectbox(
            "Batterie",
            options=options,
            index=initial_index,
            key="planning_battery_select",
        )
    else:
        selected_display = labeled_selectbox(
            "Batterie",
            options=options,
            key="planning_battery_select",
        )
    selected = resolve_label_select(selected_display, id_by_display)
    is_new = selected == NEW_OPTION
    existing = battery_map.get(selected, {}) if not is_new else {}
    if not is_new:
        st.session_state[_SESSION_SELECTED_ID_KEY] = selected

    session_scope = _battery_session_scope(selected, is_new=is_new)
    file_stamp = _config_file_stamp()
    _sync_battery_session(session_scope, existing, file_stamp=file_stamp)

    label = labeled_text_input(
        "Bezeichnung",
        key=_scoped_key(session_scope, "planning_battery_label"),
    )
    stable_id = "" if is_new else str(existing.get("id", ""))

    capacity = labeled_number_input(
        "Kapazität (kWh)",
        min_value=0.1,
        step=0.5,
        key=_scoped_key(session_scope, "planning_battery_capacity"),
    )
    max_power = labeled_number_input(
        "Max. Lade-/Entladeleistung (kW)",
        min_value=0.1,
        step=0.1,
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, "planning_battery_power"),
    )
    efficiency = labeled_number_input(
        "Wirkungsgrad",
        min_value=0.5,
        max_value=1.0,
        step=0.01,
        key=_scoped_key(session_scope, "planning_battery_efficiency"),
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
        help="Anteil der max. Lade-/Entladeleistung.",
        key=_scoped_key(session_scope, "planning_battery_threshold"),
    )

    ready = bool(str(label or "").strip()) and float(capacity or 0) > 0
    taken = {bid for bid in battery_ids if bid != stable_id}
    entity_id = stable_id.strip() or slug_id(label or "batterie", existing=taken)
    payload = {
        "id": entity_id,
        "label": label,
        "battery_capacity_kwh": capacity,
        "battery_max_power_kw": max_power,
        "battery_efficiency": efficiency,
        "battery_min_soc": min_soc,
        "battery_max_soc": max_soc,
        "threshold_power": threshold_percent / 100.0,
    }

    def _save_battery() -> None:
        try:
            upsert_battery(
                {
                    "label": label,
                    "battery_capacity_kwh": capacity,
                    "battery_max_power_kw": max_power,
                    "battery_efficiency": efficiency,
                    "battery_min_soc": min_soc,
                    "battery_max_soc": max_soc,
                    "threshold_power": threshold_percent / 100.0,
                },
                stable_id=stable_id,
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
        if is_new:
            st.session_state[_SESSION_SELECT_PENDING_KEY] = entity_id
            st.session_state[_SESSION_SYNC_KEY] = None
            st.rerun()

    wrote = auto_persist(
        state_key=f"planning_battery::{entity_id}",
        payload=payload,
        save=_save_battery,
        ready=ready,
    )
    if wrote:
        st.rerun()
