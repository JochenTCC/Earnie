"""Scenario editor tab sections (identity, entities, persist)."""
from __future__ import annotations

import streamlit as st

from ui.form_layout import labeled_checkbox
from ui.house_config_io import (
    delete_scenario,
    list_batteries,
    list_export_tariffs,
    list_import_tariffs,
    list_pv_systems,
    load_backtesting_scenarios_raw,
    load_house_profiles,
    upsert_scenario,
)
from ui.pages.scenario_editor_tariffs import (
    _seed_scenario_tariff_land,
    _user_fixed_cents_from_session,
)

# Local copies avoid circular import with page_scenario_editor → form → sections.
_SESSION_FILE_STAMP_KEY = "scenario_editor_file_stamp"
_SESSION_SELECT_PENDING_KEY = "scenario_select_pending"
_SESSION_SYNC_KEY = "scenario_editor_sync_id"
_SESSION_TEMPLATE_SOURCE_KEY = "scenario_editor_template_source"
from ui.scenario_form_helpers import (
    NEW_SCENARIO_OPTION,
    backtesting_scenarios_file_stamp,
    build_scenario_settings,
    lookup_entity_id,
    new_scenario_template,
    ordered_user_scenario_ids,
    options_for_entities,
    render_entity_multiselect,
    render_entity_selectbox,
    render_profile_geo_caption,
    resolve_scenario_id,
    scenario_session_scope,
    scoped_widget_key,
    store_scenario_form_baseline,
)


def _load_scenario_catalogs() -> dict:
    from house_config.tariffs_store import ensure_user_fixed_option

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
    batteries = list_batteries()
    pv_systems = list_pv_systems()
    import_tariffs = ensure_user_fixed_option(list_import_tariffs())
    export_tariffs = ensure_user_fixed_option(list_export_tariffs())
    profiles = load_house_profiles().get("profiles", {})
    return {
        "scenarios": scenarios,
        "scenario_labels": scenario_labels,
        "file_order_ids": file_order_ids,
        "batteries": batteries,
        "pv_systems": pv_systems,
        "import_tariffs": import_tariffs,
        "export_tariffs": export_tariffs,
        "profiles": profiles,
    }


def _entity_option_maps(catalogs: dict) -> dict:
    _, prof_map = options_for_entities(list(catalogs["profiles"].values()), allow_none=True)
    _, bat_map = options_for_entities(catalogs["batteries"], allow_none=True)
    _, pv_map = options_for_entities(catalogs["pv_systems"], allow_none=True)
    _, imp_map = options_for_entities(catalogs["import_tariffs"], allow_none=True)
    _, exp_map = options_for_entities(catalogs["export_tariffs"], allow_none=True)
    required_lists_empty = not (
        catalogs["import_tariffs"] and catalogs["export_tariffs"] and catalogs["profiles"]
    )
    return {
        "prof_map": prof_map,
        "bat_map": bat_map,
        "pv_map": pv_map,
        "imp_map": imp_map,
        "exp_map": exp_map,
        "required_lists_empty": required_lists_empty,
    }


def _resolve_and_sync_scenario(live_id: str, catalogs: dict) -> dict:
    from ui.pages.scenario_editor_session import (
        _resolve_scenario_selection,
        _sync_scenario_session,
    )

    scenario_ids = ordered_user_scenario_ids(
        catalogs["file_order_ids"],
        live_scenario_id=live_id,
        labels=catalogs["scenario_labels"],
    )
    selected = _resolve_scenario_selection(
        scenario_ids=scenario_ids,
        scenario_labels=catalogs["scenario_labels"],
        live_id=live_id,
        profiles=catalogs["profiles"],
        batteries=catalogs["batteries"],
        pv_systems=catalogs["pv_systems"],
        import_tariffs=catalogs["import_tariffs"],
        export_tariffs=catalogs["export_tariffs"],
    )
    resolved = _scenario_template_and_scope(live_id, catalogs, selected, scenario_ids)
    _sync_scenario_session(
        resolved["session_scope"],
        resolved["scenario_template"],
        file_stamp=backtesting_scenarios_file_stamp(),
        profiles=catalogs["profiles"],
        batteries=catalogs["batteries"],
        pv_systems=catalogs["pv_systems"],
        import_tariffs=catalogs["import_tariffs"],
        export_tariffs=catalogs["export_tariffs"],
    )
    return resolved


def _scenario_template_and_scope(
    live_id: str,
    catalogs: dict,
    selected: str,
    scenario_ids: list[str],
) -> dict:
    is_new = selected == NEW_SCENARIO_OPTION
    existing = (
        next((s for s in catalogs["scenarios"] if s.get("id") == selected), None)
        if not is_new
        else None
    )
    source_id = str(
        st.session_state.get(_SESSION_TEMPLATE_SOURCE_KEY) or live_id or ""
    ).strip()
    scenario_template = (
        new_scenario_template(catalogs["scenarios"], source_id=source_id, live_id=live_id)
        if is_new
        else dict(existing or {})
    )
    return {
        "scenario_ids": scenario_ids,
        "selected": selected,
        "is_new": is_new,
        "existing": existing,
        "scenario_template": scenario_template,
        "session_scope": scenario_session_scope(selected, is_new=is_new),
        "stable_scenario_id": (
            "" if is_new else str(existing.get("id", "")).strip() if existing else str(selected)
        ),
    }


def _prepare_scenario_tab(live_id: str) -> dict:
    from ui.pages.scenario_editor_session import _apply_pending_scenario_select

    _apply_pending_scenario_select()
    catalogs = _load_scenario_catalogs()
    resolved = _resolve_and_sync_scenario(live_id, catalogs)
    maps = _entity_option_maps(catalogs)
    return {"live_id": live_id, **catalogs, **resolved, **maps}


def _render_scenario_identity_fields(ctx: dict) -> str:
    existing = ctx["existing"]
    live_id = ctx["live_id"]
    session_scope = ctx["session_scope"]
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
    return label


def _render_imported_pv_option(session_scope: str, selected_profile: dict) -> None:
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
        return
    st.session_state[scoped_widget_key(session_scope, "scenario_use_imported_pv")] = False
    st.caption(
        "Kein PV-Jahresprofil im Hausprofil — Option „Importiertes PV nutzen“ nicht verfügbar."
    )


def _render_scenario_entity_picks(ctx: dict) -> dict:
    session_scope = ctx["session_scope"]
    profiles = ctx["profiles"]
    profile_col, battery_col, pv_col = st.columns(3)
    prof_pick = render_entity_selectbox(
        "Hausprofil",
        list(profiles.values()),
        allow_none=True,
        key=scoped_widget_key(session_scope, "scenario_profile"),
        container=profile_col,
    )
    selected_profile_id = lookup_entity_id(ctx["prof_map"], prof_pick)
    selected_profile = profiles.get(selected_profile_id, {})
    if selected_profile:
        with profile_col:
            render_profile_geo_caption(selected_profile)

    profile_land = str(selected_profile.get("land") or "AT").strip().upper()
    if profile_land not in {"AT", "DE", "CH"}:
        profile_land = "AT"
    land_key = _seed_scenario_tariff_land(
        session_scope, selected_profile_id, profile_land
    )
    if not selected_profile_id:
        with profile_col:
            st.caption(
                "Kein Hausprofil gewählt — Land-Filter Standard AT. "
                "Bitte Land im Hauskonfigurator (Standort) setzen."
            )

    battery_picks = render_entity_multiselect(
        "Batterien",
        ctx["batteries"],
        key=scoped_widget_key(session_scope, "scenario_battery"),
        container=battery_col,
    )
    pv_picks = render_entity_multiselect(
        "PV-Anlagen",
        ctx["pv_systems"],
        key=scoped_widget_key(session_scope, "scenario_pv"),
        container=pv_col,
    )
    _render_imported_pv_option(session_scope, selected_profile)
    return {
        "prof_pick": prof_pick,
        "battery_pick": battery_picks,
        "battery_picks": battery_picks,
        "pv_picks": pv_picks,
        "selected_profile_id": selected_profile_id,
        "selected_profile": selected_profile,
        "profile_land": profile_land,
        "land_key": land_key,
    }


def _scenario_persist_payload(
    ctx: dict,
    label: str,
    picks: dict,
    tariffs: dict,
) -> tuple[str, bool, dict]:
    session_scope = ctx["session_scope"]
    save_id = resolve_scenario_id(
        is_new=ctx["is_new"],
        existing_id=ctx["stable_scenario_id"],
        label=str(label or "").strip(),
        scenario_ids=set(ctx["scenario_ids"]),
    )
    ready = (
        not ctx["required_lists_empty"]
        and bool(save_id)
        and bool(str(label or "").strip())
    )
    import_tariff_id = lookup_entity_id(ctx["imp_map"], tariffs["imp_pick"])
    export_tariff_id = lookup_entity_id(ctx["exp_map"], tariffs["exp_pick"])
    user_import_cent, user_export_cent = _user_fixed_cents_from_session(
        session_scope, import_tariff_id, export_tariff_id
    )
    battery_picks = picks.get("battery_picks") or picks.get("battery_pick") or []
    if isinstance(battery_picks, str):
        battery_picks = [battery_picks]
    settings = build_scenario_settings(
        battery_ids=[
            lookup_entity_id(ctx["bat_map"], pick)
            for pick in battery_picks
            if lookup_entity_id(ctx["bat_map"], pick)
        ],
        pv_system_ids=[
            lookup_entity_id(ctx["pv_map"], pick)
            for pick in picks["pv_picks"]
            if lookup_entity_id(ctx["pv_map"], pick)
        ],
        import_tariff_id=import_tariff_id,
        export_tariff_id=export_tariff_id,
        house_profile_id=lookup_entity_id(ctx["prof_map"], picks["prof_pick"]),
        use_imported_pv=bool(
            st.session_state.get(
                scoped_widget_key(session_scope, "scenario_use_imported_pv"),
                False,
            )
        ),
        user_import_cent_kwh=user_import_cent,
        user_export_cent_kwh=user_export_cent,
    )
    payload = {
        "id": save_id,
        "label": str(label or "").strip() or save_id,
        "enabled": bool(
            st.session_state.get(scoped_widget_key(session_scope, "scenario_enabled"), True)
        ),
        "own_reference": bool(
            st.session_state.get(
                scoped_widget_key(session_scope, "scenario_own_reference"),
                False,
            )
        ),
        "settings": settings,
    }
    return save_id, ready, payload


def _auto_persist_scenario(
    ctx: dict,
    save_id: str,
    payload: dict,
    ready: bool,
) -> None:
    from ui.auto_persist import auto_persist

    def _save_scenario() -> None:
        try:
            upsert_scenario(payload)
        except ValueError as exc:
            st.error(str(exc))
            return
        if ctx["is_new"]:
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
        store_scenario_form_baseline(st.session_state, ctx["session_scope"], payload)
        st.rerun()


def _render_scenario_delete_button(ctx: dict) -> None:
    if ctx["is_new"] or not ctx["stable_scenario_id"]:
        return
    if ctx["stable_scenario_id"] == ctx["live_id"]:
        return
    if not st.button("Szenario entfernen", key="scenario_delete"):
        return
    try:
        delete_scenario(ctx["stable_scenario_id"])
    except ValueError as exc:
        st.error(str(exc))
        return
    st.session_state[_SESSION_SELECT_PENDING_KEY] = ctx["live_id"]
    st.session_state[_SESSION_SYNC_KEY] = None
    st.session_state[_SESSION_FILE_STAMP_KEY] = None
    st.success("Szenario entfernt.")
    st.rerun()


def _persist_or_delete_scenario(
    ctx: dict,
    label: str,
    picks: dict,
    tariffs: dict,
) -> None:
    save_id, ready, payload = _scenario_persist_payload(ctx, label, picks, tariffs)
    _auto_persist_scenario(ctx, save_id, payload, ready)
    _render_scenario_delete_button(ctx)
