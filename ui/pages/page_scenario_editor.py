"""Szenarienkonfigurator: Live-Szenario und weitere Szenario-Explorer-Varianten."""
from __future__ import annotations

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


def _remember_template_source(scenario_id: str) -> None:
    sid = str(scenario_id or "").strip()
    if sid and sid != NEW_SCENARIO_OPTION:
        st.session_state[_SESSION_TEMPLATE_SOURCE_KEY] = sid


def _planning_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz_name = config.CONFIG.get_planning_timezone()
    return datetime.now(ZoneInfo(tz_name))






def _scenario_explorer_ui_enabled() -> bool:
    from ui.mode_selector import get_enabled_ui_mode_keys

    return "scenario_explorer" in get_enabled_ui_mode_keys()




















def render() -> None:
    render_page_title_with_help(
        "🧪 Szenarienkonfigurator",
        _HELP,
        key="scenario_editor_help",
        page_docs_key="scenario-editor",
    )
    st.caption(f"Datei: `{resolve_backtesting_scenarios_json_path()}`")

    catalog_meta = load_tariffs_catalog_meta()
    if catalog_meta.get("catalog_as_of"):
        st.caption(f"Tarifkatalog: Stand {catalog_meta['catalog_as_of']}")

    _render_scenarios_tab()

from ui.pages.scenario_editor_session import (  # noqa: E402
    _SESSION_ACTIVE_SELECT_KEY,
    _SESSION_FILE_STAMP_KEY,
    _SESSION_SELECT_PENDING_KEY,
    _SESSION_SWITCH_DISCARD_KEY,
    _SESSION_SWITCH_TARGET_KEY,
    _SESSION_SYNC_KEY,
    _SESSION_TEMPLATE_SOURCE_KEY,
    _apply_pending_scenario_select,
    _ensure_active_scenario_select,
    _resolve_scenario_selection,
    _scenario_widget_state_missing,
    _seed_own_reference_widget,
    _seed_scenario_widget_state,
    _sync_scenario_session,
)
from ui.pages.scenario_editor_form import (  # noqa: E402
    _next_month_in_planning_tz,
    _render_next_month_rate_entry,
    _render_scenario_reorder_controls,
    _render_scenarios_tab,
)
