"""Passthrough merge and save UI for Hausprofil form."""
from __future__ import annotations

from ui.house_config_profile_session import (
    _SESSION_CONSUMERS_KEY,
    _SESSION_FILE_STAMP_KEY,
    _SESSION_SELECT_PENDING_KEY,
    _SESSION_SYNC_KEY,
    _consumers_from_existing,
    _house_profiles_file_stamp,
    _resolve_profile_id,
)

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
from house_config.entity_id_lock import (
    FORCE_ID_FROM_LABEL_KEY,
    ID_LOCKED_KEY,
    ID_PROVISIONAL_LABEL_KEY,
    resolve_id_on_save,
    rewrite_consumer_bindings_slug,
)
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
    ID_LOCKED_KEY,
    ID_PROVISIONAL_LABEL_KEY,
)

def _merge_passthrough_consumer_fields(original: dict, edited: dict) -> dict:
    merged = dict(edited)
    for key in _PASSTHROUGH_CONSUMER_KEYS:
        if key not in original or key in merged:
            continue
        value = original[key]
        merged[key] = dict(value) if isinstance(value, dict) else value
    orig_sched = original.get("charging_schedule")
    if isinstance(orig_sched, dict):
        sched = dict(merged.get("charging_schedule") or {})
        sched_updated = False
        loxone = orig_sched.get("loxone")
        if isinstance(loxone, dict) and "loxone" not in sched:
            sched["loxone"] = dict(loxone)
            sched_updated = True
        milp = orig_sched.get("milp")
        if isinstance(milp, dict) and milp and "milp" not in sched:
            sched["milp"] = dict(milp)
            sched_updated = True
        if sched_updated:
            merged["charging_schedule"] = sched
    return merged

def _resolve_consumer_ids(consumers: list[dict], edited: list[dict]) -> list[dict]:
    taken: set[str] = set()
    resolved: list[dict] = []
    for index, raw_item in enumerate(edited):
        item = dict(raw_item)
        force = bool(item.pop(FORCE_ID_FROM_LABEL_KEY, False))
        label = str(item.get("label", "")).strip()
        original = consumers[index] if index < len(consumers) else {}
        stable_id = str(original.get("id", "")).strip()
        provisional_ui = str(
            item.get(ID_PROVISIONAL_LABEL_KEY)
            or original.get(ID_PROVISIONAL_LABEL_KEY)
            or ""
        ).strip()
        consumer_id, id_locked, provisional = resolve_id_on_save(
            label=label or "verbraucher",
            stable_id=stable_id,
            existing=original if isinstance(original, dict) else None,
            taken=taken,
            provisional_from_ui=provisional_ui,
            force_from_label=force,
        )
        item = _merge_passthrough_consumer_fields(original, item)
        if stable_id and stable_id != consumer_id:
            bindings = item.get("ehal_bindings")
            item["ehal_bindings"] = rewrite_consumer_bindings_slug(
                bindings if isinstance(bindings, dict) else {},
                old_id=stable_id,
                new_id=consumer_id,
            )
        item["id"] = consumer_id
        item["label"] = label or consumer_id
        # Avoid dirty-writing id_locked onto legacy rows (missing flag ⇒ locked)
        # so Hausprofil auto_persist does not rewrite every open.
        if not id_locked:
            item[ID_LOCKED_KEY] = False
            if provisional:
                item[ID_PROVISIONAL_LABEL_KEY] = provisional
            else:
                item.pop(ID_PROVISIONAL_LABEL_KEY, None)
        elif (
            ID_LOCKED_KEY in original
            or force
            or (stable_id and stable_id != consumer_id)
        ):
            item[ID_LOCKED_KEY] = True
            item.pop(ID_PROVISIONAL_LABEL_KEY, None)
        else:
            item.pop(ID_LOCKED_KEY, None)
            item.pop(ID_PROVISIONAL_LABEL_KEY, None)
        taken.add(consumer_id)
        resolved.append(item)
    return resolved

def _perform_house_profile_save(
    *,
    is_new: bool,
    stable_profile_id: str,
    label: str,
    profile_ids: list[str],
    annual_kwh: float,
    location: dict,
    resolved: list[dict],
    existing: dict,
    preview_id: str,
    absent_mode: bool = False,
    from_auto: bool = False,
) -> str | None:
    profile_id = _resolve_profile_id(
        is_new=is_new,
        existing_id=stable_profile_id,
        label=label,
        profile_ids=set(profile_ids),
    )
    try:
        from ui.house_config_historical_csv import historical_csv_save_fields

        hist = historical_csv_save_fields(preview_id, existing)
        upsert_house_profile(
            {
                "id": profile_id,
                "label": label.strip() or profile_id,
                "annual_kwh": float(annual_kwh),
                "absent_mode": bool(absent_mode),
                "land": location.get("land", "AT"),
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "default_pv_tilt": location["default_pv_tilt"],
                "default_pv_azimuth": location["default_pv_azimuth"],
                "netznutzung_arbeitspreis_cent_kwh": float(
                    location.get("netznutzung_arbeitspreis_cent_kwh", 0.0) or 0.0
                ),
                "consumers": resolved,
                "total_profile_csv": hist["total_profile_csv"],
                "pv_profile_csv": hist["pv_profile_csv"],
                "battery_profile_csv": hist.get("battery_profile_csv", ""),
                "grid_profile_csv": hist.get("grid_profile_csv", ""),
                "historical_csv_source": hist["historical_csv_source"],
                "baseload_distribution": hist.get(
                    "baseload_distribution", "equal"
                ),
            }
        )
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.session_state[_SESSION_FILE_STAMP_KEY] = _house_profiles_file_stamp()
    if is_new:
        saved_profile = load_house_profiles().get("profiles", {}).get(profile_id, {})
        st.session_state[_SESSION_SELECT_PENDING_KEY] = profile_id
        st.session_state[_SESSION_SYNC_KEY] = None
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(saved_profile)
        st.rerun()
    elif not from_auto:
        saved_profile = load_house_profiles().get("profiles", {}).get(profile_id, {})
        st.session_state[_SESSION_SELECT_PENDING_KEY] = profile_id
        st.session_state[_SESSION_SYNC_KEY] = None
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(saved_profile)
        st.success("Profil gespeichert.")
        st.rerun()
    return profile_id

def _render_house_profile_save(
    *,
    session_scope: str,
    is_new: bool,
    stable_profile_id: str,
    label: str,
    profile_ids: list[str],
    annual_kwh: float,
    location: dict,
    resolved: list[dict],
    existing: dict,
    preview_id: str,
    absent_mode: bool = False,
) -> None:
    from ui.auto_persist import auto_persist
    from ui.house_config_historical_csv import historical_csv_save_fields

    ready = bool(str(label or "").strip()) and location.get("latitude") is not None
    if not ready:
        return
    hist = historical_csv_save_fields(preview_id, existing)
    profile_id = _resolve_profile_id(
        is_new=is_new,
        existing_id=stable_profile_id,
        label=label,
        profile_ids=set(profile_ids),
    )
    payload = {
        "id": profile_id,
        "label": label.strip() or profile_id,
        "annual_kwh": float(annual_kwh),
        "absent_mode": bool(absent_mode),
        "land": location.get("land", "AT"),
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "default_pv_tilt": location["default_pv_tilt"],
        "default_pv_azimuth": location["default_pv_azimuth"],
        "netznutzung_arbeitspreis_cent_kwh": float(
            location.get("netznutzung_arbeitspreis_cent_kwh", 0.0) or 0.0
        ),
        "consumers": resolved,
        "total_profile_csv": hist["total_profile_csv"],
        "pv_profile_csv": hist["pv_profile_csv"],
        "battery_profile_csv": hist.get("battery_profile_csv", ""),
        "grid_profile_csv": hist.get("grid_profile_csv", ""),
        "historical_csv_source": hist["historical_csv_source"],
        "baseload_distribution": hist.get("baseload_distribution", "equal"),
    }

    def _save() -> None:
        _perform_house_profile_save(
            is_new=is_new,
            stable_profile_id=stable_profile_id,
            label=label,
            profile_ids=profile_ids,
            annual_kwh=annual_kwh,
            absent_mode=absent_mode,
            location=location,
            resolved=resolved,
            existing=existing,
            preview_id=preview_id,
            from_auto=True,
        )

    wrote = auto_persist(
        state_key=f"house_profile::{session_scope}::{profile_id}",
        payload=payload,
        save=_save,
        ready=ready,
    )
    # Refresh Profil dropdown labels from disk (auto-save previously skipped st.rerun).
    if wrote:
        st.rerun()
