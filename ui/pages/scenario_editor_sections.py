"""Scenario editor tab sections (identity, entities, tariffs, persist)."""
from __future__ import annotations

import streamlit as st

import config
from ui.doc_links import DocLink, markdown_doc_link
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
    upsert_scenario,
)
from ui.pages.page_scenario_editor import (
    _planning_now,
    _SESSION_FILE_STAMP_KEY,
    _SESSION_SELECT_PENDING_KEY,
    _SESSION_SYNC_KEY,
    _SESSION_TEMPLATE_SOURCE_KEY,
)
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
from ui.tariff_filter_helpers import (
    render_shared_land_filter,
    render_tariff_parameter_preview,
    render_tariff_type_filter,
)


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


def _load_scenario_catalogs() -> dict:
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
    import_tariffs = list_import_tariffs()
    export_tariffs = list_export_tariffs()
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


def _seed_scenario_tariff_land(
    session_scope: str,
    selected_profile_id: str,
    profile_land: str,
) -> str:
    land_key = scoped_widget_key(session_scope, "scenario_tariff_land")
    land_seed_key = scoped_widget_key(session_scope, "scenario_tariff_land_profile")
    if (
        land_seed_key not in st.session_state
        or st.session_state.get(land_seed_key) != selected_profile_id
    ):
        st.session_state[land_key] = profile_land
        st.session_state[land_seed_key] = selected_profile_id
    return land_key


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

    battery_pick = render_entity_selectbox(
        "Batterie",
        ctx["batteries"],
        allow_none=True,
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
        "battery_pick": battery_pick,
        "pv_picks": pv_picks,
        "selected_profile_id": selected_profile_id,
        "selected_profile": selected_profile,
        "profile_land": profile_land,
        "land_key": land_key,
    }


def _current_tariff_ids_from_session(ctx: dict, session_scope: str) -> tuple[str | None, str | None]:
    scenario_settings = ctx["scenario_template"].get("settings") or {}
    current_import_id = str(scenario_settings.get("import_tariff_id") or "").strip() or None
    current_export_id = str(scenario_settings.get("export_tariff_id") or "").strip() or None
    import_key = scoped_widget_key(session_scope, "scenario_import")
    export_key = scoped_widget_key(session_scope, "scenario_export")
    if import_key in st.session_state:
        current_import_id = (
            lookup_entity_id(ctx["imp_map"], st.session_state.get(import_key))
            or current_import_id
        )
    if export_key in st.session_state:
        current_export_id = (
            lookup_entity_id(ctx["exp_map"], st.session_state.get(export_key))
            or current_export_id
        )
    return current_import_id, current_export_id


def _render_scenario_tariff_filters(
    ctx: dict,
    picks: dict,
    current_import_id: str | None,
    current_export_id: str | None,
) -> tuple[list, list]:
    session_scope = ctx["session_scope"]
    land_col, import_type_col, export_type_col = st.columns(3)
    shared_land = render_shared_land_filter(
        key=picks["land_key"],
        import_tariffs=ctx["import_tariffs"],
        export_tariffs=ctx["export_tariffs"],
        default_land=picks["profile_land"],
        container=land_col,
    )
    filtered_imports = render_tariff_type_filter(
        key_prefix=scoped_widget_key(session_scope, "scenario_import_filter"),
        tariffs=ctx["import_tariffs"],
        kind="import",
        land=shared_land,
        current_id=current_import_id,
        label_prefix="Bezug ",
        container=import_type_col,
    )
    filtered_exports = render_tariff_type_filter(
        key_prefix=scoped_widget_key(session_scope, "scenario_export_filter"),
        tariffs=ctx["export_tariffs"],
        kind="export",
        land=shared_land,
        current_id=current_export_id,
        label_prefix="Einspeise ",
        container=export_type_col,
    )
    return filtered_imports, filtered_exports


def _render_scenario_tariff_picks(
    ctx: dict,
    filtered_imports: list,
    filtered_exports: list,
    current_import_id: str | None,
    current_export_id: str | None,
) -> tuple[object, object]:
    session_scope = ctx["session_scope"]
    import_key = scoped_widget_key(session_scope, "scenario_import")
    export_key = scoped_widget_key(session_scope, "scenario_export")
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
    return imp_pick, exp_pick


def _render_scenario_tariff_previews(
    ctx: dict,
    selected_import: str | None,
    selected_export: str | None,
) -> tuple[dict | None, dict | None]:
    import_tariff = None
    export_tariff = None
    _, import_param_col, export_param_col = st.columns(3)
    if selected_import:
        import_tariff = next(t for t in ctx["import_tariffs"] if t["id"] == selected_import)
        render_tariff_parameter_preview(
            import_tariff,
            title="Bezugstarif-Parameter",
            kind="import",
            container=import_param_col,
        )
    if selected_export:
        export_tariff = next(t for t in ctx["export_tariffs"] if t["id"] == selected_export)
        render_tariff_parameter_preview(
            export_tariff,
            title="Einspeisetarif-Parameter",
            kind="export",
            container=export_param_col,
        )
    return import_tariff, export_tariff


def _render_scenario_next_month_rates(
    ctx: dict,
    import_tariff: dict | None,
    export_tariff: dict | None,
) -> None:
    from data.tariff_pricing import is_within_days_of_next_month

    if not is_within_days_of_next_month(_planning_now(), days=2):
        return
    next_y, next_m = _next_month_in_planning_tz()
    if import_tariff is not None:
        _render_next_month_rate_entry(
            tariff=import_tariff,
            side="import",
            year=next_y,
            month=next_m,
            session_scope=ctx["session_scope"],
        )
    if export_tariff is not None:
        _render_next_month_rate_entry(
            tariff=export_tariff,
            side="export",
            year=next_y,
            month=next_m,
            session_scope=ctx["session_scope"],
        )


def _render_tariff_catalog_notice(selected_import: str | None, selected_export: str | None) -> None:
    if not (selected_import or selected_export):
        return
    st.info(
        "Bitte prüfen Sie die angezeigten Tarifdaten. Es gibt keine Garantie "
        "für Vollständigkeit oder Aktualität des Katalogs. Monatliche Fixkosten "
        "(Grundgebühr o. Ä.) fließen als **Näherung** in die Gesamtkosten und "
        "Monatswerte des Szenario-Explorers ein — nicht in die Live-MILP-Kosten. "
        "Volumetrische **Netznutzung Arbeitspreis** kommt aus dem Hausprofil "
        "(nicht aus dem Lieferantentarif). "
        f"Nachrechnen: "
        f"{markdown_doc_link(DocLink('Tarife und Preise nachrechnen', 'docs/referenz/tarife-quellen.md'))}."
    )


def _render_scenario_tariff_block(ctx: dict, picks: dict) -> dict:
    session_scope = ctx["session_scope"]
    current_import_id, current_export_id = _current_tariff_ids_from_session(
        ctx, session_scope
    )
    filtered_imports, filtered_exports = _render_scenario_tariff_filters(
        ctx, picks, current_import_id, current_export_id
    )
    imp_pick, exp_pick = _render_scenario_tariff_picks(
        ctx, filtered_imports, filtered_exports, current_import_id, current_export_id
    )
    selected_import = lookup_entity_id(ctx["imp_map"], imp_pick)
    selected_export = lookup_entity_id(ctx["exp_map"], exp_pick)
    import_tariff, export_tariff = _render_scenario_tariff_previews(
        ctx, selected_import, selected_export
    )
    _render_scenario_next_month_rates(ctx, import_tariff, export_tariff)
    _render_tariff_catalog_notice(selected_import, selected_export)
    return {"imp_pick": imp_pick, "exp_pick": exp_pick}


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
    settings = build_scenario_settings(
        battery_id=lookup_entity_id(ctx["bat_map"], picks["battery_pick"]),
        pv_system_ids=[
            lookup_entity_id(ctx["pv_map"], pick)
            for pick in picks["pv_picks"]
            if lookup_entity_id(ctx["pv_map"], pick)
        ],
        import_tariff_id=lookup_entity_id(ctx["imp_map"], tariffs["imp_pick"]),
        export_tariff_id=lookup_entity_id(ctx["exp_map"], tariffs["exp_pick"]),
        house_profile_id=lookup_entity_id(ctx["prof_map"], picks["prof_pick"]),
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
