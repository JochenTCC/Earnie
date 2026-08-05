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


def _next_month_in_planning_tz() -> tuple[int, int]:
    from data.tariff_pricing import next_calendar_month

    now = _planning_now()
    return next_calendar_month(now.year, now.month)


def _render_next_month_rate_entry(
    *,
    tariff: dict,
    side: str,
    year: int,
    month: int,
    session_scope: str,
) -> None:
    """Warn + form when next calendar month is missing on a monthly_table tariff."""
    from data.tariff_pricing import monthly_rates_cover_month

    if str(tariff.get("type", "")).strip().lower() != "monthly_table":
        return
    if monthly_rates_cover_month(tariff, year, month):
        return

    side_label = "Bezug" if side == "import" else "Einspeise"
    tariff_label = str(tariff.get("label") or tariff.get("id") or side)
    st.warning(
        f"{side_label}tarif „{tariff_label}“ hat keinen Eintrag für "
        f"{year}-{month:02d} (nächster Monat). Bis zur Aktualisierung "
        "wird temporär der Vorjahres- bzw. Vormonatswert verwendet. "
        "Bitte den aktuellen Cent/kWh-Wert eintragen:"
    )
    cent_key = scoped_widget_key(session_scope, f"next_month_cent_{side}")
    cols = st.columns([1, 1, 2, 1])
    cols[0].markdown(f"**Jahr**  \n{year}")
    cols[1].markdown(f"**Monat**  \n{month}")
    cent = cols[2].number_input(
        "Cent/kWh",
        min_value=0.01,
        step=0.01,
        format="%.3f",
        key=cent_key,
        help=f"Wird in tariffs.json für {tariff['id']} ergänzt.",
    )
    if cols[3].button(
        "Speichern",
        key=scoped_widget_key(session_scope, f"next_month_save_{side}"),
    ):
        try:
            append_tariff_monthly_rate(
                side=side,
                tariff_id=str(tariff["id"]),
                year=year,
                month=month,
                tariff_cent_kwh=float(cent),
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        st.rerun()


def _scenario_explorer_ui_enabled() -> bool:
    from ui.mode_selector import get_enabled_ui_mode_keys

    return "scenario_explorer" in get_enabled_ui_mode_keys()


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
    st.session_state[scoped_widget_key(session_scope, "scenario_netzentgelt")] = float(
        settings.get("netzentgelt_cent_kwh_override", 0.0) or 0.0
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


def _render_scenario_reorder_controls(
    *,
    selected: str,
    scenario_ids: list[str],
    live_id: str,
    container=None,
) -> None:
    root = container if container is not None else st
    non_live = [sid for sid in scenario_ids if sid != live_id]
    can_reorder = (
        selected != NEW_SCENARIO_OPTION
        and selected != live_id
        and selected in non_live
    )
    root.caption("Live bleibt oben.")
    if not can_reorder:
        root.button(
            "↑",
            key="scenario_reorder_up",
            disabled=True,
            help="Szenario nach oben verschieben",
        )
        root.button(
            "↓",
            key="scenario_reorder_down",
            disabled=True,
            help="Szenario nach unten verschieben",
        )
        return
    idx = non_live.index(selected)
    if root.button(
        "↑",
        key="scenario_reorder_up",
        disabled=idx <= 0,
        help="Szenario nach oben verschieben",
    ):
        ordered = list(non_live)
        ordered[idx - 1], ordered[idx] = ordered[idx], ordered[idx - 1]
        try:
            reorder_scenarios(ordered)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state[_SESSION_SELECT_PENDING_KEY] = selected
        st.session_state[_SESSION_FILE_STAMP_KEY] = backtesting_scenarios_file_stamp()
        st.rerun()
    if root.button(
        "↓",
        key="scenario_reorder_down",
        disabled=idx >= len(non_live) - 1,
        help="Szenario nach unten verschieben",
    ):
        ordered = list(non_live)
        ordered[idx + 1], ordered[idx] = ordered[idx], ordered[idx + 1]
        try:
            reorder_scenarios(ordered)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state[_SESSION_SELECT_PENDING_KEY] = selected
        st.session_state[_SESSION_FILE_STAMP_KEY] = backtesting_scenarios_file_stamp()
        st.rerun()


def _render_scenarios_tab() -> None:
    live_id = config.get_live_scenario_id()
    st.subheader("Szenarien")
    st.caption(
        "Live-Szenario ist die Baseline für Szenario-Explorer "
        "und Echtzeit-Betrieb. Standort und Zeitzone kommen aus dem Hausprofil."
    )

    _apply_pending_scenario_select()
    scenarios_doc = load_backtesting_scenarios_raw()
    scenarios = scenarios_doc.get("scenarios", [])
    scenario_labels = {
        str(s.get("id", "")).strip(): str(s.get("label") or s.get("id") or "").strip()
        for s in scenarios
        if str(s.get("id", "")).strip()
    }
    file_order_ids = [
        str(s.get("id", "")).strip()
        for s in scenarios
        if str(s.get("id", "")).strip()
    ]
    scenario_ids = ordered_user_scenario_ids(
        file_order_ids,
        live_scenario_id=live_id,
        labels=scenario_labels,
    )
    batteries = list_batteries()
    pv_systems = list_pv_systems()
    import_tariffs = list_import_tariffs()
    export_tariffs = list_export_tariffs()
    profiles = load_house_profiles().get("profiles", {})

    selected = _resolve_scenario_selection(
        scenario_ids=scenario_ids,
        scenario_labels=scenario_labels,
        live_id=live_id,
        profiles=profiles,
        batteries=batteries,
        pv_systems=pv_systems,
        import_tariffs=import_tariffs,
        export_tariffs=export_tariffs,
    )

    is_new = selected == NEW_SCENARIO_OPTION
    existing = next((s for s in scenarios if s.get("id") == selected), None) if not is_new else None
    scenario_template = (
        new_scenario_template(
            scenarios,
            source_id=str(
                st.session_state.get(_SESSION_TEMPLATE_SOURCE_KEY) or live_id or ""
            ).strip(),
            live_id=live_id,
        )
        if is_new
        else dict(existing or {})
    )
    session_scope = scenario_session_scope(selected, is_new=is_new)
    stable_scenario_id = "" if is_new else str(existing.get("id", "")).strip() if existing else str(selected)

    _sync_scenario_session(
        session_scope,
        scenario_template,
        file_stamp=backtesting_scenarios_file_stamp(),
        profiles=profiles,
        batteries=batteries,
        pv_systems=pv_systems,
        import_tariffs=import_tariffs,
        export_tariffs=export_tariffs,
    )

    if existing and str(existing.get("id", "")).strip() == live_id:
        st.info(
            "Dies ist das Live-Szenario. Die Bezeichnung kann nicht geändert werden."
        )

    is_live = bool(existing) and str(existing.get("id", "")).strip() == live_id
    label_key = scoped_widget_key(session_scope, "scenario_label")
    enabled_key = scoped_widget_key(session_scope, "scenario_enabled")
    own_ref_key = scoped_widget_key(session_scope, "scenario_own_reference")

    label_col, enabled_col, own_ref_col = st.columns(3)
    label = label_col.text_input(
        "Bezeichnung",
        key=label_key,
        disabled=is_live,
    )
    if is_live and existing:
        label = str(existing.get("label") or existing.get("id") or "").strip()
    enabled_col.checkbox(
        "Aktiv für Szenario-Explorer",
        key=enabled_key,
        help=(
            "Deaktivierte Szenarien erscheinen nicht in der SE-Berechnung. "
            "Änderungen machen vorhandene SE-Ergebnisse ungültig."
        ),
    )
    own_ref_col.checkbox(
        "Eigene Referenz ohne Optimierung",
        key=own_ref_key,
        help=(
            "Berechnet eine eigene Nicht-Opt-Referenz (Tarif + PV) für dieses Szenario. "
            "Ohne gespeicherten Wert vorbelegt aus Earnies Heuristik "
            "(eigene Referenz nur bei abweichendem Tarif/PV; Batterie-Varianten teilen "
            "die Live-Referenz). Aus = Live-Referenz bzw. Historisch teilen. "
            "Änderungen machen vorhandene SE-Ergebnisse ungültig."
        ),
    )

    _, prof_map = options_for_entities(list(profiles.values()), allow_none=True)
    _, bat_map = options_for_entities(batteries, allow_none=True)
    _, pv_map = options_for_entities(pv_systems, allow_none=True)
    _, imp_map = options_for_entities(import_tariffs, allow_none=True)
    _, exp_map = options_for_entities(export_tariffs, allow_none=True)

    required_lists_empty = not (import_tariffs and export_tariffs and profiles)

    profile_col, battery_col, pv_col = st.columns(3)
    prof_pick = render_entity_selectbox(
        "Hausprofil",
        list(profiles.values()),
        allow_none=True,
        key=scoped_widget_key(session_scope, "scenario_profile"),
        container=profile_col,
    )
    selected_profile_id = lookup_entity_id(prof_map, prof_pick)
    selected_profile = profiles.get(selected_profile_id, {})
    if selected_profile:
        with profile_col:
            render_profile_geo_caption(selected_profile)

    profile_land = str(selected_profile.get("land") or "AT").strip().upper()
    if profile_land not in {"AT", "DE", "CH"}:
        profile_land = "AT"
    land_key = scoped_widget_key(session_scope, "scenario_tariff_land")
    land_seed_key = scoped_widget_key(session_scope, "scenario_tariff_land_profile")
    if (
        land_seed_key not in st.session_state
        or st.session_state.get(land_seed_key) != selected_profile_id
    ):
        st.session_state[land_key] = profile_land
        st.session_state[land_seed_key] = selected_profile_id
    if not selected_profile_id:
        with profile_col:
            st.caption(
                "Kein Hausprofil gewählt — Land-Filter Standard AT. "
                "Bitte Land im Hauskonfigurator (Standort) setzen."
            )

    battery_pick = render_entity_selectbox(
        "Batterie",
        batteries,
        allow_none=True,
        key=scoped_widget_key(session_scope, "scenario_battery"),
        container=battery_col,
    )
    pv_picks = render_entity_multiselect(
        "PV-Anlagen",
        pv_systems,
        key=scoped_widget_key(session_scope, "scenario_pv"),
        container=pv_col,
    )
    has_pv_csv = bool(str(selected_profile.get("pv_profile_csv", "") or "").strip())
    if has_pv_csv:
        labeled_checkbox(
            "Importiertes PV-Profil statt PV aus Wetterdaten nutzen",
            key=scoped_widget_key(session_scope, "scenario_use_imported_pv"),
            help=(
                "Nutzt das PV-Jahresprofil aus dem Hausprofil (`pv_profile_csv`) "
                "als Summe für die Szenario-Explorer-Berechnung statt Open-Meteo."
            ),
        )
    else:
        st.session_state[scoped_widget_key(session_scope, "scenario_use_imported_pv")] = False
        st.caption(
            "Kein PV-Jahresprofil im Hausprofil — Option „Importiertes PV nutzen“ nicht verfügbar."
        )
    scenario_settings = scenario_template.get("settings") or {}
    current_import_id = str(scenario_settings.get("import_tariff_id") or "").strip() or None
    current_export_id = str(scenario_settings.get("export_tariff_id") or "").strip() or None
    import_key = scoped_widget_key(session_scope, "scenario_import")
    export_key = scoped_widget_key(session_scope, "scenario_export")
    if import_key in st.session_state:
        current_import_id = (
            lookup_entity_id(imp_map, st.session_state.get(import_key)) or current_import_id
        )
    if export_key in st.session_state:
        current_export_id = (
            lookup_entity_id(exp_map, st.session_state.get(export_key)) or current_export_id
        )

    land_col, import_type_col, export_type_col = st.columns(3)
    shared_land = render_shared_land_filter(
        key=land_key,
        import_tariffs=import_tariffs,
        export_tariffs=export_tariffs,
        default_land=profile_land,
        container=land_col,
    )
    filtered_imports = render_tariff_type_filter(
        key_prefix=scoped_widget_key(session_scope, "scenario_import_filter"),
        tariffs=import_tariffs,
        kind="import",
        land=shared_land,
        current_id=current_import_id,
        label_prefix="Bezug ",
        container=import_type_col,
    )
    filtered_exports = render_tariff_type_filter(
        key_prefix=scoped_widget_key(session_scope, "scenario_export_filter"),
        tariffs=export_tariffs,
        kind="export",
        land=shared_land,
        current_id=current_export_id,
        label_prefix="Einspeise ",
        container=export_type_col,
    )

    _, import_pick_col, export_pick_col = st.columns(3)
    imp_pick = render_entity_selectbox(
        "Bezugstarif",
        filtered_imports,
        allow_none=True,
        key=import_key,
        current_id=current_import_id,
        container=import_pick_col,
    )
    exp_pick = render_entity_selectbox(
        "Einspeisetarif",
        filtered_exports,
        allow_none=True,
        key=export_key,
        current_id=current_export_id,
        container=export_pick_col,
    )
    selected_import = lookup_entity_id(imp_map, imp_pick)
    selected_export = lookup_entity_id(exp_map, exp_pick)
    import_tariff = None
    export_tariff = None
    netzentgelt_override = None
    _, import_param_col, export_param_col = st.columns(3)
    if selected_import:
        import_tariff = next(t for t in import_tariffs if t["id"] == selected_import)
        render_tariff_parameter_preview(
            import_tariff,
            title="Bezugstarif-Parameter",
            kind="import",
            container=import_param_col,
        )
        if import_tariff.get("land") == "DE" and import_tariff.get("type") in {
            "spot_hourly",
            "ex_post_spot",
            "monthly_market",
        }:
            netzentgelt_override = import_param_col.number_input(
                "Netzentgelt-Override (Cent/kWh, DE-Spot)",
                min_value=0.0,
                step=0.1,
                key=scoped_widget_key(session_scope, "scenario_netzentgelt"),
            )
    if selected_export:
        export_tariff = next(t for t in export_tariffs if t["id"] == selected_export)
        render_tariff_parameter_preview(
            export_tariff,
            title="Einspeisetarif-Parameter",
            kind="export",
            container=export_param_col,
        )
    from data.tariff_pricing import is_within_days_of_next_month

    if is_within_days_of_next_month(_planning_now(), days=2):
        next_y, next_m = _next_month_in_planning_tz()
        if import_tariff is not None:
            _render_next_month_rate_entry(
                tariff=import_tariff,
                side="import",
                year=next_y,
                month=next_m,
                session_scope=session_scope,
            )
        if export_tariff is not None:
            _render_next_month_rate_entry(
                tariff=export_tariff,
                side="export",
                year=next_y,
                month=next_m,
                session_scope=session_scope,
            )
    if selected_import or selected_export:
        st.info(
            "Bitte prüfen Sie die angezeigten Tarifdaten. Es gibt keine Garantie "
            "für Vollständigkeit oder Aktualität des Katalogs. Monatliche Fixkosten "
            "(Grundgebühr o. Ä.) fließen als **Näherung** in die Gesamtkosten und "
            "Monatswerte des Szenario-Explorers ein — nicht in die Live-MILP-Kosten. "
            f"Nachrechnen: "
            f"{markdown_doc_link(DocLink('Tarife und Preise nachrechnen', 'docs/referenz/tarife-quellen.md'))}."
        )

    from ui.auto_persist import auto_persist

    save_id = resolve_scenario_id(
        is_new=is_new,
        existing_id=stable_scenario_id,
        label=str(label or "").strip(),
        scenario_ids=set(scenario_ids),
    )
    ready = (
        not required_lists_empty
        and bool(save_id)
        and bool(str(label or "").strip())
    )
    settings = build_scenario_settings(
        battery_id=lookup_entity_id(bat_map, battery_pick),
        pv_system_ids=[
            lookup_entity_id(pv_map, pick)
            for pick in pv_picks
            if lookup_entity_id(pv_map, pick)
        ],
        import_tariff_id=lookup_entity_id(imp_map, imp_pick),
        export_tariff_id=lookup_entity_id(exp_map, exp_pick),
        house_profile_id=lookup_entity_id(prof_map, prof_pick),
        netzentgelt_cent_kwh_override=netzentgelt_override,
        use_imported_pv=bool(
            st.session_state.get(
                scoped_widget_key(session_scope, "scenario_use_imported_pv"),
                False,
            )
        ),
    )
    payload = {
        "id": save_id,
        "label": str(label or "").strip() or save_id,
        "enabled": bool(
            st.session_state.get(
                scoped_widget_key(session_scope, "scenario_enabled"),
                True,
            )
        ),
        "own_reference": bool(
            st.session_state.get(
                scoped_widget_key(session_scope, "scenario_own_reference"),
                False,
            )
        ),
        "settings": settings,
    }

    def _save_scenario() -> None:
        try:
            upsert_scenario(payload)
        except ValueError as exc:
            st.error(str(exc))
            return
        if is_new:
            st.session_state[_SESSION_SELECT_PENDING_KEY] = save_id
            st.rerun()

    wrote = auto_persist(
        state_key=f"scenario::{save_id}",
        payload=payload,
        save=_save_scenario,
        ready=ready,
    )
    if wrote:
        # Avoid treating our own write as file_changed (would clear Land/Typ filters).
        st.session_state[_SESSION_FILE_STAMP_KEY] = backtesting_scenarios_file_stamp()
        store_scenario_form_baseline(st.session_state, session_scope, payload)
        st.rerun()

    if not is_new and stable_scenario_id and stable_scenario_id != live_id:
        if st.button("Szenario entfernen", key="scenario_delete"):
            try:
                delete_scenario(stable_scenario_id)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state[_SESSION_SELECT_PENDING_KEY] = live_id
                st.session_state[_SESSION_SYNC_KEY] = None
                st.session_state[_SESSION_FILE_STAMP_KEY] = None
                st.success("Szenario entfernt.")
                st.rerun()


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
