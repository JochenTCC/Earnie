"""Scenario editor tab sections (identity, entities, persist)."""
from __future__ import annotations

from datetime import date

import streamlit as st

from runtime_store.shadow.errors import ConfigReadOnlyError
from ui.auto_persist import SHADOW_READONLY_CAPTION
from ui.flash import flash
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
    REF_FIELD_LABELS_DE,
    backtesting_scenarios_file_stamp,
    build_scenario_settings,
    carry_missing_refs,
    drop_missing_refs,
    hidden_scenario_settings,
    missing_scenario_refs,
    normalize_scenario_form_snapshot,
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
    from house_config.powerstation import scenario_selectable_batteries
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
    # Powerstations attach via consumers — never offer them as scenario battery picks.
    batteries = scenario_selectable_batteries(list_batteries())
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

    label_col, enabled_col = st.columns(2)
    label = label_col.text_input(
        "Bezeichnung",
        key=label_key,
        disabled=is_live,
    )
    if is_live and existing:
        label = str(existing.get("label") or existing.get("id") or "").strip()
    if is_live:
        # Live always runs in the SE: every other scenario is compared with it.
        st.session_state[enabled_key] = True
    enabled_col.checkbox(
        "Aktiv für Szenario-Explorer",
        key=enabled_key,
        disabled=is_live,
        help=(
            "Das Live-Szenario läuft im Szenario-Explorer immer, alle anderen werden mit ihm "
            "verglichen."
            if is_live
            else "Deaktivierte Szenarien erscheinen nicht in der SE-Berechnung. "
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
        "PV-Felder",
        ctx["pv_systems"],
        key=scoped_widget_key(session_scope, "scenario_pv"),
        container=pv_col,
    )
    _render_imported_pv_option(session_scope, selected_profile)
    from ui.scenario_heating_picks import render_heating_picks

    heating_picks = render_heating_picks(
        session_scope,
        selected_profile,
        is_live=bool(ctx["live_id"]) and ctx["stable_scenario_id"] == ctx["live_id"],
    )
    return {
        "heating_system_ids": heating_picks,
        "prof_pick": prof_pick,
        "battery_pick": battery_picks,
        "battery_picks": battery_picks,
        "pv_picks": pv_picks,
        "selected_profile_id": selected_profile_id,
        "selected_profile": selected_profile,
        "profile_land": profile_land,
        "land_key": land_key,
    }


def _import_cap_grid_fee(picks: dict):
    """Edibert grid fee of the picked house profile; ``None`` without profile or area."""
    from house_config import edibert_tariffs as eb
    from runtime_store.persist_paths import resolve_grid_fees_json_path

    profile = picks.get("selected_profile") or {}
    if not profile.get("netznutzung"):
        return None
    catalog = eb.cached_grid_fees(resolve_grid_fees_json_path())
    return eb.profile_grid_fee(str(picks.get("selected_profile_id") or ""), profile, catalog)


def _render_scenario_import_cap(ctx: dict, picks: dict) -> tuple[str, ...]:
    """Cap and margin for the capacity charge; returns the errors that stop saving."""
    from house_config.edibert_tariffs import EdibertLoadError
    from house_config.import_cap import (
        IMPORT_CAP_KEY,
        IMPORT_CAP_MARGIN_KEY,
        IMPORT_CAP_MODE_LABELS_DE,
        IMPORT_CAP_MODES,
        check_import_cap,
        parse_import_cap,
    )

    session_scope = ctx["session_scope"]
    cap_col, margin_col = st.columns(2)
    cap_kw = cap_col.number_input(
        "Bezugsgrenze [kW]",
        min_value=0.1,
        step=0.1,
        format="%.2f",
        value=None,
        placeholder="∞ (keine Grenze)",
        key=scoped_widget_key(session_scope, "scenario_import_cap"),
        help=(
            "Für den Leistungspreis: Der Plan hält den Netzbezug je Viertelstunde unter dieser "
            "Grenze. Leer = keine Grenze. Wirkt nur in Monaten mit Leistungspreis im Netzbereich. "
            "Eine enge Grenze kann mehr kosten, als sie spart. "
            "Änderungen machen vorhandene SE-Ergebnisse ungültig."
        ),
    )
    margin_kw = margin_col.number_input(
        "Sicherheitsmarge [kW]",
        min_value=0.0,
        step=0.1,
        format="%.2f",
        key=scoped_widget_key(session_scope, "scenario_import_cap_margin"),
        disabled=cap_kw is None,
        help="Der Plan zielt auf die Bezugsgrenze minus diese Marge, wegen Prognose- und Messfehlern.",
    )
    st.radio(
        "Im Live-Betrieb",
        options=list(IMPORT_CAP_MODES),
        format_func=IMPORT_CAP_MODE_LABELS_DE.__getitem__,
        horizontal=True,
        key=scoped_widget_key(session_scope, "scenario_import_cap_mode"),
        disabled=cap_kw is None,
        help=(
            "Beobachten: Earnie plant und steuert wie ohne Grenze und zeigt auf dem Monitor, wo und "
            "wie er eingegriffen hätte und was das gespart hätte. Danach planen: Earnie hält die "
            "Grenze ein. Gilt nur, wenn dieses Szenario das Live-Szenario ist; die Szenario-"
            "Simulation plant immer mit der Grenze."
        ),
    )
    if cap_kw is None:
        return ()
    try:
        cap = parse_import_cap({IMPORT_CAP_KEY: cap_kw, IMPORT_CAP_MARGIN_KEY: margin_kw})
        check = check_import_cap(cap, _import_cap_grid_fee(picks), date.today())
    except (ValueError, EdibertLoadError) as exc:
        st.error(str(exc))
        return (str(exc),)
    for error in check.errors:
        st.error(error)
    for note in check.notes:
        st.info(note)
    return check.errors


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
        heating_system_ids=picks.get("heating_system_ids"),
        import_cap_kw=st.session_state.get(scoped_widget_key(session_scope, "scenario_import_cap")),
        import_cap_margin_kw=st.session_state.get(
            scoped_widget_key(session_scope, "scenario_import_cap_margin")
        ),
        import_cap_mode=st.session_state.get(
            scoped_widget_key(session_scope, "scenario_import_cap_mode")
        ),
    )
    template = ctx["scenario_template"]
    stored_settings = dict(template.get("settings") or {})
    # The form shows only part of a scenario: settings it does not show (flat overrides such as
    # pv_kwp) and references it cannot offer (deleted entries) are written back unchanged.
    settings = {
        **hidden_scenario_settings(stored_settings),
        **carry_missing_refs(settings, _missing_refs(ctx, stored_settings)),
    }
    payload = {
        key: value
        for key, value in template.items()
        if key not in ("id", "label", "enabled", "settings")
    }
    payload.update(
        {
            "id": save_id,
            "label": str(label or "").strip() or save_id,
            "enabled": bool(
                st.session_state.get(scoped_widget_key(session_scope, "scenario_enabled"), True)
            ),
            "settings": settings,
        }
    )
    return save_id, ready, payload


def _missing_refs(ctx: dict, stored_settings: dict) -> dict[str, list[str]]:
    return missing_scenario_refs(
        stored_settings,
        profiles=ctx["profiles"],
        batteries=ctx["batteries"],
        pv_systems=ctx["pv_systems"],
        import_tariffs=ctx["import_tariffs"],
        export_tariffs=ctx["export_tariffs"],
    )


def _render_missing_refs_notice(ctx: dict) -> None:
    """Name references to entries the form cannot offer; remove them only on request."""
    stored_settings = dict(ctx["scenario_template"].get("settings") or {})
    missing = _missing_refs(ctx, stored_settings)
    if not missing:
        return
    names = ", ".join(
        f"{REF_FIELD_LABELS_DE[field]} „{ref}“" for field, ids in missing.items() for ref in ids
    )
    st.warning(
        f"Dieses Szenario verweist auf Einträge, die es nicht (mehr) gibt oder die hier nicht "
        f"wählbar sind: {names}. Sie bleiben im Szenario, bis du einen anderen Eintrag wählst "
        "oder sie hier entfernst."
    )
    if ctx["is_new"] or not ctx["existing"]:
        return
    if not st.button(
        "Fehlende Verweise entfernen",
        key=scoped_widget_key(ctx["session_scope"], "scenario_drop_missing_refs"),
    ):
        return
    existing = dict(ctx["existing"])
    existing["settings"] = drop_missing_refs(stored_settings, missing)
    try:
        upsert_scenario(existing)
    except ValueError as exc:
        st.error(str(exc))
        return
    flash("success", "Fehlende Verweise entfernt.")
    st.rerun()


def _matches_stored_scenario(ctx: dict, payload: dict) -> bool:
    """True when a save would write what the file already holds for this scenario."""
    existing = ctx["existing"]
    if ctx["is_new"] or not existing:
        return False
    if hidden_scenario_settings(existing.get("settings") or {}) != hidden_scenario_settings(
        payload["settings"]
    ):
        return False
    return normalize_scenario_form_snapshot(payload) == normalize_scenario_form_snapshot(
        existing
    )


def _auto_persist_scenario(
    ctx: dict,
    save_id: str,
    payload: dict,
    ready: bool,
) -> None:
    from ui.auto_persist import PersistRejected, auto_persist, seed_persisted

    state_key = f"scenario::{save_id}"
    if _matches_stored_scenario(ctx, payload):
        # Opening a scenario (or editing back to the file) writes nothing; auto_persist below
        # still shows the "Gespeichert" flash of the write before.
        seed_persisted(state_key, payload)
        ready = False

    def _save_scenario() -> None:
        try:
            upsert_scenario(payload)
        except ValueError as exc:
            st.error(str(exc))
            raise PersistRejected() from exc
        if ctx["is_new"]:
            st.session_state[_SESSION_SELECT_PENDING_KEY] = save_id
            st.rerun()

    wrote = auto_persist(
        state_key=state_key,
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
    from ui.auto_persist import forget_persisted

    try:
        delete_scenario(ctx["stable_scenario_id"])
    except ConfigReadOnlyError:
        st.caption(SHADOW_READONLY_CAPTION)
        return
    except ValueError as exc:
        st.error(str(exc))
        return
    # A new scenario with the same id and content must be written again.
    forget_persisted(f"scenario::{ctx['stable_scenario_id']}")
    st.session_state[_SESSION_SELECT_PENDING_KEY] = ctx["live_id"]
    st.session_state[_SESSION_SYNC_KEY] = None
    st.session_state[_SESSION_FILE_STAMP_KEY] = None
    flash("success", "Szenario entfernt.")
    st.rerun()


def _persist_or_delete_scenario(
    ctx: dict,
    label: str,
    picks: dict,
    tariffs: dict,
    import_cap_errors: tuple[str, ...] = (),
) -> None:
    _render_missing_refs_notice(ctx)
    save_id, ready, payload = _scenario_persist_payload(ctx, label, picks, tariffs)
    _auto_persist_scenario(ctx, save_id, payload, ready and not import_cap_errors)
    _render_scenario_delete_button(ctx)
