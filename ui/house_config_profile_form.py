"""Hausprofil-Tab im Hauskonfigurator."""
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








































































































def _render_profile_selector() -> dict:
    _apply_pending_profile_select()
    profiles_doc = load_house_profiles()
    profile_map = profiles_doc.get("profiles", {})
    profile_ids = sorted(profile_map.keys())
    profile_options, id_by_display = _profile_select_choices(profile_map, profile_ids)
    _align_profile_select_session(profile_map, profile_ids, id_by_display)
    initial_index = _initial_profile_index(profile_ids)
    if initial_index is not None:
        selected_display = labeled_selectbox(
            "Profil",
            options=profile_options,
            index=initial_index,
            key="house_profile_select",
        )
    else:
        selected_display = labeled_selectbox(
            "Profil",
            options=profile_options,
            key="house_profile_select",
        )
    selected_id = id_by_display.get(str(selected_display), str(selected_display))
    is_new = selected_id == _NEW_PROFILE_OPTION
    existing = profile_map.get(selected_id, {}) if not is_new else {}
    session_scope = _profile_session_scope(selected_id, is_new=is_new)
    if not is_new:
        st.session_state[_SESSION_SELECTED_ID_KEY] = selected_id
    _sync_profile_session(
        session_scope,
        existing,
        file_stamp=_house_profiles_file_stamp(),
        siblings=list(profile_map.values()),
    )
    return {
        "profile_ids": profile_ids,
        "is_new": is_new,
        "existing": existing,
        "stable_profile_id": str(existing.get("id", "")).strip(),
        "session_scope": session_scope,
    }


def _edit_and_sync_consumers(session_scope: str, location: dict) -> tuple[list, list]:
    st.subheader("Verbraucher")
    st.caption(
        "Optional — ohne Verbraucher gilt der gesamte Jahresverbrauch als Grundlast. "
        "„Haus Wärme“ ist nicht erforderlich."
    )
    consumers = list(st.session_state.get(_SESSION_CONSUMERS_KEY, []))
    if st.button("Verbraucher hinzufügen", key=_scoped_key(session_scope, "house_consumer_add")):
        st.session_state[_SESSION_CONSUMERS_KEY].append(_default_additional_consumer())
        st.rerun()
    edited = [
        _render_consumer_form(
            consumer,
            index,
            latitude=location["latitude"],
            longitude=location["longitude"],
            session_scope=session_scope,
            default_pv_tilt=location["default_pv_tilt"],
            default_pv_azimuth=location["default_pv_azimuth"],
        )
        for index, consumer in enumerate(consumers)
    ]
    # Keep session list in sync with edited fields so expander titles
    # (consumer_annual_kwh from schedule/nominal/thermal) stay correct next run.
    synced_consumers = []
    for index, original in enumerate(consumers):
        if index < len(edited):
            merged = _merge_passthrough_consumer_fields(original, dict(edited[index]))
            if original.get("id"):
                merged["id"] = original["id"]
        else:
            merged = dict(original)
        synced_consumers.append(merged)
    st.session_state[_SESSION_CONSUMERS_KEY] = synced_consumers
    resolved = _resolve_consumer_ids(synced_consumers, edited)
    resolved_for_preview = _inject_profile_geo(
        resolved,
        location["latitude"],
        location["longitude"],
        timezone_name=str(location.get("timezone_name") or ""),
    )
    return resolved, resolved_for_preview


def _render_baseload_preview(
    annual_kwh: float,
    resolved_for_preview: list,
    existing: dict,
    preview_id: str,
) -> dict:
    preview = preview_baseload(annual_kwh, resolved_for_preview)
    csv_session_key = f"house_profile_csv_path_{preview_id}"
    preview["total_profile_csv"] = str(
        st.session_state.get(
            csv_session_key,
            existing.get("total_profile_csv", ""),
        )
        or ""
    ).strip()
    st.metric("Verbraucher-Summe (kWh/a)", f"{preview['consumer_kwh']:.0f}")
    st.metric("Grundlast (kWh/a)", f"{preview['baseload_kwh']:.0f}")
    st.caption(
        f"Roh-Differenz {preview['raw_baseload_kwh']:.0f} kWh/a; "
        f"Untergrenze 2 % = {preview['baseload_min_kwh']:.0f} kWh/a"
    )
    return preview


def _render_profile_identity(ctx: dict) -> tuple[str, str, float, dict]:
    session_scope = ctx["session_scope"]
    label = labeled_text_input(
        "Bezeichnung",
        key=_scoped_key(session_scope, "house_profile_label"),
    )
    preview_id = _resolve_profile_id(
        is_new=ctx["is_new"],
        existing_id=ctx["stable_profile_id"],
        label=label,
        profile_ids=set(ctx["profile_ids"]),
    )
    annual_kwh = labeled_number_input(
        "Jahresverbrauch (kWh/a)",
        min_value=0.0,
        step=100.0,
        key=_scoped_key(session_scope, "house_annual_kwh"),
    )
    location = _render_location_fields(session_scope=session_scope)
    from ui.ehal_greenfield_import import render_greenfield_import_section

    render_greenfield_import_section()
    return label, preview_id, float(annual_kwh), location


def render_house_profile_tab() -> None:
    ctx = _render_profile_selector()
    label, preview_id, annual_kwh, location = _render_profile_identity(ctx)
    resolved, resolved_for_preview = _edit_and_sync_consumers(
        ctx["session_scope"], location
    )
    preview = _render_baseload_preview(
        annual_kwh, resolved_for_preview, ctx["existing"], preview_id
    )
    save_kwargs = {
        "session_scope": ctx["session_scope"],
        "is_new": ctx["is_new"],
        "stable_profile_id": ctx["stable_profile_id"],
        "label": label,
        "profile_ids": ctx["profile_ids"],
        "annual_kwh": annual_kwh,
        "location": location,
        "resolved": resolved,
        "existing": ctx["existing"],
        "preview_id": preview_id,
    }
    _render_house_profile_save(**save_kwargs)
    _render_consumption_csv_section(
        existing=ctx["existing"],
        preview_id=preview_id,
        annual_kwh=annual_kwh,
        resolved=resolved_for_preview,
        preview=preview,
    )
    _render_house_profile_save(**save_kwargs)

from ui.house_config_profile_session import (  # noqa: E402
    CONSUMER_TYPE_OPTIONS,
    _NEW_PROFILE_OPTION,
    _SESSION_CONSUMERS_KEY,
    _SESSION_FILE_STAMP_KEY,
    _SESSION_SELECT_PENDING_KEY,
    _SESSION_SELECTED_ID_KEY,
    _SESSION_SYNC_KEY,
    _align_profile_select_session,
    _apply_pending_profile_select,
    _clear_consumer_widget_keys,
    _clear_scoped_widget_keys,
    _consumer_type_options,
    _consumers_from_existing,
    _default_additional_consumer,
    _default_consumer,
    _flatten_consumer_for_edit,
    _house_profiles_file_stamp,
    _initial_profile_index,
    _live_markers_enabled,
    _profile_display_label,
    _profile_select_choices,
    _profile_session_scope,
    _profile_widget_state_missing,
    _resolve_profile_id,
    _scoped_key,
    _seed_profile_widget_state,
    _sync_profile_session,
    _type_index,
)
from ui.house_config_profile_generic import (  # noqa: E402
    _EARNIE_ROLE_LABELS,
    _EARNIE_ROLE_OPTIONS,
    _loxone_inputs_from_consumer,
    _preserved_appliance_power_source,
    _render_generic_fields,
    _render_manual_appliance_defaults,
    _render_manual_power_source,
    _schedule_defaults,
)
from ui.house_config_profile_ev import (  # noqa: E402
    _apply_ev_default_widget_keys,
    _default_ev_consumer,
    _render_day_schedule,
    _render_ev_fields,
    _seed_ev_defaults_on_type_switch,
)
from ui.house_config_profile_thermal import (  # noqa: E402
    _consumer_expander_title,
    _inject_profile_geo,
    _live_consumer_for_annual,
    _render_location_fields,
    _render_thermal_annual_fields,
    _render_thermal_rc_fields,
    _render_thermal_solar_fields,
)
from ui.house_config_profile_csv import (  # noqa: E402
    _digital_csv_decision_key,
    _ensure_consumer_csv_normalized,
    _render_consumption_csv_section,
    _render_consumer_profile_csv_fields,
    _render_digital_csv_scale_prompt,
)
from ui.house_config_profile_save import (  # noqa: E402
    _PASSTHROUGH_CONSUMER_KEYS,
    _merge_passthrough_consumer_fields,
    _perform_house_profile_save,
    _render_house_profile_save,
    _resolve_consumer_ids,
)
from ui.house_config_profile_consumers import (  # noqa: E402
    _render_consumer_form,
    _render_consumer_form_body,
)

# Re-Exports für API-Stabilität (from ui.house_config_profile_form import ...)
__all__ = [
    "CONSUMER_TYPE_OPTIONS",
    "_PASSTHROUGH_CONSUMER_KEYS",
    "_consumer_expander_title",
    "_consumer_type_options",
    "_default_additional_consumer",
    "_default_consumer",
    "_default_ev_consumer",
    "_flatten_consumer_for_edit",
    "_inject_profile_geo",
    "_live_markers_enabled",
    "_merge_passthrough_consumer_fields",
    "_preserved_appliance_power_source",
    "_profile_session_scope",
    "_schedule_defaults",
    "_seed_ev_defaults_on_type_switch",
    "_seed_profile_widget_state",
    "_sync_profile_session",
    "render_house_profile_tab",
]
