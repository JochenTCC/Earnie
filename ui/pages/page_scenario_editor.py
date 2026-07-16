"""Szenarieneditor: Live-Szenario und weitere Szenario-Explorer-Varianten."""
from __future__ import annotations

import streamlit as st

import config
from ui.help_hint import render_page_title_with_help
from ui.house_config_io import (
    list_batteries,
    list_export_tariffs,
    list_import_tariffs,
    list_pv_systems,
    load_backtesting_scenarios_raw,
    load_house_profiles,
    load_tariffs_catalog_meta,
    upsert_scenario,
)
from ui.planning_tariff_form import (
    _EXPORT_TYPE_LABELS,
    _IMPORT_TYPE_LABELS,
    _tariff_meta_caption,
    _type_caption,
)
from ui.scenario_form_helpers import (
    NEW_SCENARIO_OPTION,
    backtesting_scenarios_file_stamp,
    build_scenario_settings,
    clear_scoped_widget_keys,
    lookup_entity_id,
    new_scenario_template,
    options_for_entities,
    render_entity_selectbox,
    render_profile_geo_caption,
    resolve_scenario_id,
    scenario_form_is_dirty,
    scenario_session_scope,
    scoped_widget_key,
    seed_entity_select_state,
    store_scenario_form_baseline,
)

_HELP = (
    "Live-Szenario (Pflicht für Echtzeit und Szenario-Explorer) und optionale "
    "weitere Varianten. Batterie-Entitäten legst du im Hauskonfigurator an; "
    "Speichert Szenarien nach `config/backtesting_scenarios.json`; Live-Auswahl über "
    "`live_scenario_id` in `config.json`."
)

_SESSION_SYNC_KEY = "scenario_editor_sync_id"
_SESSION_FILE_STAMP_KEY = "scenario_editor_file_stamp"
_SESSION_SELECT_PENDING_KEY = "scenario_select_pending"
_SESSION_ACTIVE_SELECT_KEY = "scenario_editor_active_select"
_SESSION_SWITCH_TARGET_KEY = "scenario_editor_switch_target"
_SESSION_SWITCH_DISCARD_KEY = "scenario_editor_switch_discard"


def _apply_pending_scenario_select() -> None:
    pending = st.session_state.pop(_SESSION_SELECT_PENDING_KEY, None)
    if pending is not None:
        st.session_state["scenario_select"] = pending
        st.session_state[_SESSION_ACTIVE_SELECT_KEY] = pending
        st.session_state.pop(_SESSION_SWITCH_TARGET_KEY, None)


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
    seed_entity_select_state(
        session_scope,
        "scenario_pv",
        pv_systems,
        settings.get("pv_system_id"),
        allow_none=True,
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
    profile = profiles.get(str(settings.get("house_profile_id", "") or "").strip(), {})
    st.session_state[scoped_widget_key(session_scope, "scenario_lat")] = float(
        settings.get("latitude", profile.get("latitude", 48.0))
    )
    st.session_state[scoped_widget_key(session_scope, "scenario_lon")] = float(
        settings.get("longitude", profile.get("longitude", 10.0))
    )
    st.session_state[scoped_widget_key(session_scope, "scenario_geo_override")] = (
        "latitude" in settings or "longitude" in settings
    )


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
        clear_scoped_widget_keys(session_scope)
        _seed_scenario_widget_state(
            session_scope,
            scenario,
            profiles=profiles,
            batteries=batteries,
            pv_systems=pv_systems,
            import_tariffs=import_tariffs,
            export_tariffs=export_tariffs,
        )
        store_scenario_form_baseline(
            st.session_state,
            session_scope,
            scenario,
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
    live_id: str,
    profiles: dict[str, dict],
    batteries: list[dict],
    pv_systems: list[dict],
    import_tariffs: list[dict],
    export_tariffs: list[dict],
) -> str:
    default_pick = live_id if live_id in scenario_ids else NEW_SCENARIO_OPTION
    _ensure_active_scenario_select(default_pick)

    if st.session_state.pop(_SESSION_SWITCH_DISCARD_KEY, False):
        target = st.session_state.pop(_SESSION_SWITCH_TARGET_KEY, None)
        if target is not None:
            st.session_state[_SESSION_ACTIVE_SELECT_KEY] = target
            st.session_state["scenario_select"] = target
            st.session_state[_SESSION_SYNC_KEY] = None
            st.rerun()

    st.selectbox(
        "Szenario",
        options=[NEW_SCENARIO_OPTION, *scenario_ids],
        key="scenario_select",
    )
    requested = st.session_state["scenario_select"]
    active = st.session_state[_SESSION_ACTIVE_SELECT_KEY]

    if requested == active and st.session_state.get(_SESSION_SWITCH_TARGET_KEY) is None:
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
        return active

    st.session_state[_SESSION_ACTIVE_SELECT_KEY] = requested
    st.session_state.pop(_SESSION_SWITCH_TARGET_KEY, None)
    return requested


def _render_scenarios_tab() -> None:
    live_id = config.get_live_scenario_id()
    st.subheader("Szenarien")
    st.caption(
        f"Live-Szenario (aktuell: `{live_id}`) ist die Baseline für Szenario-Explorer "
        "und Echtzeit-Betrieb. Standort und Zeitzone kommen aus dem Hausprofil."
    )

    _apply_pending_scenario_select()
    scenarios_doc = load_backtesting_scenarios_raw()
    scenarios = scenarios_doc.get("scenarios", [])
    scenario_ids = [s.get("id", "") for s in scenarios]

    batteries = list_batteries()
    pv_systems = list_pv_systems()
    import_tariffs = list_import_tariffs()
    export_tariffs = list_export_tariffs()
    profiles = load_house_profiles().get("profiles", {})

    selected = _resolve_scenario_selection(
        scenario_ids=scenario_ids,
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
        new_scenario_template(live_id, scenarios) if is_new else dict(existing or {})
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
        st.info(f"Dies ist das Live-Szenario (`live_scenario_id`: `{live_id}`).")

    label = st.text_input(
        "Bezeichnung",
        key=scoped_widget_key(session_scope, "scenario_label"),
    )
    preview_id = resolve_scenario_id(
        is_new=is_new,
        existing_id=stable_scenario_id,
        label=label,
        scenario_ids=set(scenario_ids),
    )
    st.caption(f"Szenario-ID: `{preview_id}`")

    _, prof_map = options_for_entities(list(profiles.values()), allow_none=True)
    _, bat_map = options_for_entities(batteries, allow_none=True)
    _, pv_map = options_for_entities(pv_systems, allow_none=True)
    _, imp_map = options_for_entities(import_tariffs, allow_none=True)
    _, exp_map = options_for_entities(export_tariffs, allow_none=True)

    required_lists_empty = not (import_tariffs and export_tariffs and profiles)

    prof_pick = render_entity_selectbox(
        "Hausprofil",
        list(profiles.values()),
        allow_none=True,
        key=scoped_widget_key(session_scope, "scenario_profile"),
    )
    selected_profile_id = lookup_entity_id(prof_map, prof_pick)
    selected_profile = profiles.get(selected_profile_id, {})
    if selected_profile:
        render_profile_geo_caption(selected_profile)

    battery_pick = render_entity_selectbox(
        "Batterie",
        batteries,
        allow_none=True,
        key=scoped_widget_key(session_scope, "scenario_battery"),
    )
    pv_pick = render_entity_selectbox(
        "PV-Anlage",
        pv_systems,
        allow_none=True,
        key=scoped_widget_key(session_scope, "scenario_pv"),
    )
    imp_pick = render_entity_selectbox(
        "Bezugstarif",
        import_tariffs,
        allow_none=True,
        key=scoped_widget_key(session_scope, "scenario_import"),
    )
    exp_pick = render_entity_selectbox(
        "Einspeisetarif",
        export_tariffs,
        allow_none=True,
        key=scoped_widget_key(session_scope, "scenario_export"),
    )
    selected_import = lookup_entity_id(imp_map, imp_pick)
    selected_export = lookup_entity_id(exp_map, exp_pick)
    if selected_import:
        import_tariff = next(t for t in import_tariffs if t["id"] == selected_import)
        st.caption(
            f"Bezug: {_type_caption(import_tariff, _IMPORT_TYPE_LABELS)}"
            + (
                f" · {_tariff_meta_caption(import_tariff)}"
                if _tariff_meta_caption(import_tariff)
                else ""
            )
        )
    if selected_export:
        export_tariff = next(t for t in export_tariffs if t["id"] == selected_export)
        st.caption(
            f"Einspeise: {_type_caption(export_tariff, _EXPORT_TYPE_LABELS)}"
            + (
                f" · {_tariff_meta_caption(export_tariff)}"
                if _tariff_meta_caption(export_tariff)
                else ""
            )
        )

    netzentgelt_override = None
    if selected_import:
        import_tariff = next(t for t in import_tariffs if t["id"] == selected_import)
        if import_tariff.get("land") == "DE" and import_tariff.get("type") in {
            "spot_hourly",
            "ex_post_spot",
            "monthly_market",
        }:
            netzentgelt_override = st.number_input(
                "Netzentgelt-Override (Cent/kWh, DE-Spot)",
                min_value=0.0,
                step=0.1,
                key=scoped_widget_key(session_scope, "scenario_netzentgelt"),
            )

    with st.expander("Standort-Override (optional, Backtesting)", expanded=False):
        st.caption(
            "Nur für What-if-Szenarien. Leer lassen = Standort/Zeitzone aus Hausprofil."
        )
        col_a, col_b = st.columns(2)
        latitude = col_a.number_input(
            "Breitengrad (Override)",
            key=scoped_widget_key(session_scope, "scenario_lat"),
        )
        longitude = col_b.number_input(
            "Längengrad (Override)",
            key=scoped_widget_key(session_scope, "scenario_lon"),
        )
        use_geo_override = st.checkbox(
            "Standort-Override in Szenario speichern",
            key=scoped_widget_key(session_scope, "scenario_geo_override"),
        )

    if st.button(
        "Szenario speichern",
        type="primary",
        key="scenario_save",
        disabled=required_lists_empty,
    ):
        save_id = resolve_scenario_id(
            is_new=is_new,
            existing_id=stable_scenario_id,
            label=str(label or "").strip(),
            scenario_ids=set(scenario_ids),
        )
        if not save_id:
            st.error("Szenario-ID konnte nicht abgeleitet werden — bitte Bezeichnung prüfen.")
        else:
            upsert_scenario(
                {
                    "id": save_id,
                    "label": str(label or "").strip() or save_id,
                    "settings": build_scenario_settings(
                        battery_id=lookup_entity_id(bat_map, battery_pick),
                        pv_system_id=lookup_entity_id(pv_map, pv_pick),
                        import_tariff_id=lookup_entity_id(imp_map, imp_pick),
                        export_tariff_id=lookup_entity_id(exp_map, exp_pick),
                        house_profile_id=lookup_entity_id(prof_map, prof_pick),
                        latitude=latitude if use_geo_override else None,
                        longitude=longitude if use_geo_override else None,
                        netzentgelt_cent_kwh_override=netzentgelt_override,
                    ),
                }
            )
            st.session_state[_SESSION_SELECT_PENDING_KEY] = save_id
            st.success(f"Szenario '{save_id}' gespeichert.")
            st.rerun()


def render() -> None:
    render_page_title_with_help("🧪 Szenarieneditor", _HELP, key="scenario_editor_help")

    catalog_meta = load_tariffs_catalog_meta()
    if catalog_meta.get("catalog_as_of"):
        st.caption(f"Tarifkatalog: Stand {catalog_meta['catalog_as_of']}")

    _render_scenarios_tab()
