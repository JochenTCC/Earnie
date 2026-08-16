"""Scenario editor session/select helpers."""
from __future__ import annotations

import config
from ui.pages.page_scenario_editor import (
    _remember_template_source,
    _scenario_explorer_ui_enabled,
)

import streamlit as st

import config
from runtime_store.persist_paths import resolve_backtesting_scenarios_json_path
from ui.doc_links import DocLink, markdown_doc_link
from ui.help_hint import render_page_title_with_help
from ui.form_layout import labeled_checkbox
from ui.house_config_io import (
    append_tariff_monthly_rate,
    delete_scenario,
    list_batteries,
    list_export_tariffs,
    list_import_tariffs,
    list_pv_systems,
    load_backtesting_scenarios_raw,
    load_house_profiles,
    load_tariffs_catalog_meta,
    reorder_scenarios,
    upsert_scenario,
)
from ui.tariff_filter_helpers import (
    render_shared_land_filter,
    render_tariff_parameter_preview,
    render_tariff_type_filter,
)
from ui.label_select import (
    label_select_choices,
    refresh_label_select_display,
    resolve_label_select,
)
from ui.scenario_form_helpers import (
    NEW_SCENARIO_OPTION,
    SCENARIO_FILTER_KEY_BASES,
    backtesting_scenarios_file_stamp,
    build_scenario_settings,
    clear_scoped_widget_keys,
    default_scenario_pick,
    lookup_entity_id,
    new_scenario_template,
    ordered_user_scenario_ids,
    options_for_entities,
    render_entity_multiselect,
    render_entity_selectbox,
    render_profile_geo_caption,
    resolve_scenario_id,
    scenario_form_is_dirty,
    scenario_new_option,
    scenario_session_scope,
    scoped_widget_key,
    seed_entity_multiselect_state,
    seed_entity_select_state,
    store_scenario_form_baseline,
)

_HELP = (
    "Live-Szenario (Pflicht für Echtzeit und Szenario-Explorer) und optionale "
    "weitere Varianten. Batterie-Entitäten legst du im Hauskonfigurator an. "
    "Speichert Szenarien nach `config/backtesting_scenarios.json`. "
    "Die Bezeichnung des Live-Szenarios ist fest; Entitäts-Referenzen sind editierbar."
)

_SESSION_SYNC_KEY = "scenario_editor_sync_id"
_SESSION_FILE_STAMP_KEY = "scenario_editor_file_stamp"
_SESSION_SELECT_PENDING_KEY = "scenario_select_pending"
_SESSION_ACTIVE_SELECT_KEY = "scenario_editor_active_select"
_SESSION_TEMPLATE_SOURCE_KEY = "scenario_editor_template_source"
_SESSION_SWITCH_TARGET_KEY = "scenario_editor_switch_target"
_SESSION_SWITCH_DISCARD_KEY = "scenario_editor_switch_discard"



def _apply_pending_scenario_select() -> None:
    pending = st.session_state.pop(_SESSION_SELECT_PENDING_KEY, None)
    if pending is not None:
        st.session_state["scenario_select"] = pending
        st.session_state[_SESSION_ACTIVE_SELECT_KEY] = pending
        st.session_state.pop(_SESSION_SWITCH_TARGET_KEY, None)
        _remember_template_source(pending)

def _seed_scenario_widget_state(
    session_scope: str,
    scenario: dict,
    *,
    profiles: dict[str, dict],
    batteries: list[dict],
    pv_systems: list[dict],
    import_tariffs: list[dict],
    export_tariffs: list[dict],
) -> None:
    settings = dict(scenario.get("settings", {}))
    st.session_state[scoped_widget_key(session_scope, "scenario_label")] = str(
        scenario.get("label", "Mein Szenario")
    )
    seed_entity_select_state(
        session_scope,
        "scenario_profile",
        list(profiles.values()),
        settings.get("house_profile_id"),
        allow_none=True,
    )
    seed_entity_select_state(
        session_scope,
        "scenario_battery",
        batteries,
        settings.get("battery_id"),
        allow_none=True,
    )
    from house_config.entity_resolution import normalize_pv_system_ids

    seed_entity_multiselect_state(
        session_scope,
        "scenario_pv",
        pv_systems,
        normalize_pv_system_ids(settings),
    )
    seed_entity_select_state(
        session_scope,
        "scenario_import",
        import_tariffs,
        settings.get("import_tariff_id"),
        allow_none=True,
    )
    seed_entity_select_state(
        session_scope,
        "scenario_export",
        export_tariffs,
        settings.get("export_tariff_id"),
        allow_none=True,
    )
    st.session_state[scoped_widget_key(session_scope, "scenario_use_imported_pv")] = bool(
        settings.get("use_imported_pv")
    )
    st.session_state[scoped_widget_key(session_scope, "scenario_enabled")] = (
        scenario.get("enabled", True) is not False
    )
    _seed_own_reference_widget(session_scope, scenario)

def _seed_own_reference_widget(session_scope: str, scenario: dict) -> None:
    key = scoped_widget_key(session_scope, "scenario_own_reference")
    if "own_reference" in scenario:
        st.session_state[key] = bool(scenario.get("own_reference"))
        return
    from simulation.engine import default_own_reference

    live_id = str(config.get_live_scenario_id() or "").strip()
    sid = str(scenario.get("id") or "").strip()
    try:
        params = config.CONFIG.resolve_scenario_settings_dict(
            dict(scenario.get("settings") or {})
        )
        live_params = None
        if live_id:
            for entry in config.get_scenarios():
                if str(entry.get("id") or "").strip() == live_id:
                    live_params = config.CONFIG.resolve_scenario_settings_dict(
                        dict(entry.get("settings") or {})
                    )
                    break
            if live_params is None and sid == live_id:
                live_params = params
        st.session_state[key] = default_own_reference(
            sid or live_id,
            params,
            live_scenario_id=live_id,
            live_params=live_params if live_params is not None else params,
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        st.session_state[key] = False

def _scenario_widget_state_missing(session_scope: str) -> bool:
    """True when sync metadata exists but scoped widget keys were dropped (e.g. page navigation)."""
    return scoped_widget_key(session_scope, "scenario_label") not in st.session_state

def _sync_scenario_session(
    session_scope: str,
    scenario: dict,
    *,
    file_stamp: str,
    profiles: dict[str, dict],
    batteries: list[dict],
    pv_systems: list[dict],
    import_tariffs: list[dict],
    export_tariffs: list[dict],
) -> None:
    scope_changed = st.session_state.get(_SESSION_SYNC_KEY) != session_scope
    file_changed = st.session_state.get(_SESSION_FILE_STAMP_KEY) != file_stamp
    widget_state_missing = _scenario_widget_state_missing(session_scope)
    if scope_changed or file_changed or widget_state_missing:
        preserve: set[str] = set()
        # Own auto_persist / external reload must not wipe Land/Typ filters.
        if file_changed and not scope_changed and not widget_state_missing:
            preserve = {
                scoped_widget_key(session_scope, base)
                for base in SCENARIO_FILTER_KEY_BASES
                if scoped_widget_key(session_scope, base) in st.session_state
            }
        clear_scoped_widget_keys(session_scope, preserve_keys=preserve)
        _seed_scenario_widget_state(
            session_scope,
            scenario,
            profiles=profiles,
            batteries=batteries,
            pv_systems=pv_systems,
            import_tariffs=import_tariffs,
            export_tariffs=export_tariffs,
        )
        baseline_scenario = dict(scenario)
        baseline_scenario["own_reference"] = bool(
            st.session_state.get(
                scoped_widget_key(session_scope, "scenario_own_reference"),
                False,
            )
        )
        store_scenario_form_baseline(
            st.session_state,
            session_scope,
            baseline_scenario,
        )
        st.session_state[_SESSION_SYNC_KEY] = session_scope
        st.session_state[_SESSION_FILE_STAMP_KEY] = file_stamp

def _ensure_active_scenario_select(default_pick: str) -> None:
    if "scenario_select" not in st.session_state:
        st.session_state["scenario_select"] = default_pick
    if _SESSION_ACTIVE_SELECT_KEY not in st.session_state:
        st.session_state[_SESSION_ACTIVE_SELECT_KEY] = st.session_state["scenario_select"]

def _resolve_scenario_selection(
    *,
    scenario_ids: list[str],
    scenario_labels: dict[str, str],
    live_id: str,
    profiles: dict[str, dict],
    batteries: list[dict],
    pv_systems: list[dict],
    import_tariffs: list[dict],
    export_tariffs: list[dict],
) -> str:
    allow_new = _scenario_explorer_ui_enabled()
    new_option = scenario_new_option(allow_new=allow_new)
    default_pick = default_scenario_pick(
        live_id=live_id,
        scenario_ids=scenario_ids,
        allow_new=allow_new,
    )
    _ensure_active_scenario_select(default_pick)

    active_now = st.session_state.get(_SESSION_ACTIVE_SELECT_KEY)
    if not allow_new and active_now == NEW_SCENARIO_OPTION:
        st.session_state[_SESSION_ACTIVE_SELECT_KEY] = default_pick
        st.session_state["scenario_select"] = default_pick
        st.session_state[_SESSION_SYNC_KEY] = None
        st.rerun()

    if st.session_state.pop(_SESSION_SWITCH_DISCARD_KEY, False):
        target = st.session_state.pop(_SESSION_SWITCH_TARGET_KEY, None)
        if target is not None:
            st.session_state[_SESSION_ACTIVE_SELECT_KEY] = target
            st.session_state["scenario_select"] = target
            st.session_state[_SESSION_SYNC_KEY] = None
            st.rerun()

    scenario_map = {
        sid: {"id": sid, "label": scenario_labels.get(sid, sid)} for sid in scenario_ids
    }
    options, id_by_display = label_select_choices(
        scenario_map, scenario_ids, new_option=new_option
    )
    refresh_label_select_display(
        select_key="scenario_select",
        selected_id=st.session_state.get(_SESSION_ACTIVE_SELECT_KEY),
        entity_map=scenario_map,
        entity_ids=scenario_ids,
        id_by_display=id_by_display,
        new_option=new_option,
    )

    list_col, reorder_col = st.columns([5, 1], vertical_alignment="top")
    list_col.radio(
        "Szenario",
        options=options,
        key="scenario_select",
    )
    requested = resolve_label_select(st.session_state["scenario_select"], id_by_display)
    active = st.session_state[_SESSION_ACTIVE_SELECT_KEY]

    from ui.pages.scenario_editor_form import _render_scenario_reorder_controls

    if requested == active and st.session_state.get(_SESSION_SWITCH_TARGET_KEY) is None:
        _render_scenario_reorder_controls(
            selected=active,
            scenario_ids=scenario_ids,
            live_id=live_id,
            container=reorder_col,
        )
        _remember_template_source(active)
        return active

    active_is_new = active == NEW_SCENARIO_OPTION
    active_scope = scenario_session_scope(active, is_new=active_is_new)
    dirty = scenario_form_is_dirty(
        st.session_state,
        active_scope,
        profiles=profiles,
        batteries=batteries,
        pv_systems=pv_systems,
        import_tariffs=import_tariffs,
        export_tariffs=export_tariffs,
    )
    if dirty:
        _render_scenario_reorder_controls(
            selected=active,
            scenario_ids=scenario_ids,
            live_id=live_id,
            container=reorder_col,
        )
        switch_target = st.session_state.get(_SESSION_SWITCH_TARGET_KEY)
        if requested != active and switch_target != requested:
            st.session_state[_SESSION_SELECT_PENDING_KEY] = active
            st.session_state[_SESSION_SWITCH_TARGET_KEY] = requested
            st.rerun()
        st.warning(
            "Es gibt ungespeicherte Änderungen am aktuellen Szenario. "
            "Wechseln und Änderungen verwerfen?"
        )
        col_discard, col_cancel = st.columns(2)
        if col_discard.button(
            "Verwerfen und wechseln",
            key="scenario_switch_discard",
        ):
            st.session_state[_SESSION_SWITCH_DISCARD_KEY] = True
            st.rerun()
        if col_cancel.button("Abbrechen", key="scenario_switch_cancel"):
            st.session_state.pop(_SESSION_SWITCH_TARGET_KEY, None)
            st.session_state[_SESSION_SELECT_PENDING_KEY] = active
            st.rerun()
        _remember_template_source(active)
        return active

    st.session_state[_SESSION_ACTIVE_SELECT_KEY] = requested
    st.session_state.pop(_SESSION_SWITCH_TARGET_KEY, None)
    _remember_template_source(requested)
    _render_scenario_reorder_controls(
        selected=requested,
        scenario_ids=scenario_ids,
        live_id=live_id,
        container=reorder_col,
    )
    return requested
