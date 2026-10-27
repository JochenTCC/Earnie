"""Scenario editor tariff filters, picks, previews, and next-month rates.

Since Edibert P7 the preview of a selected tariff is Edibert's (``render_preview``) and user
tariffs are edited on the Tarife page (embedded Edibert editor), linked from here.
"""
from __future__ import annotations

import streamlit as st

from ui.doc_links import DocLink, markdown_doc_link
from ui.house_config_io import append_tariff_monthly_rate
from ui.scenario_form_helpers import (
    lookup_entity_id,
    render_entity_selectbox,
    scoped_widget_key,
)
from ui.tariff_filter_helpers import (
    render_shared_land_filter,
    render_tariff_type_filter,
)

_TARIFFS_PAGE_URL = "tariffs"


def _planning_now_for_tariffs():
    # Late import: page_scenario_editor imports form which imports this module.
    from ui.pages.page_scenario_editor import _planning_now

    return _planning_now()


def _is_user_tariff(tariff: dict | None) -> bool:
    from house_config.tariffs_store import ORIGIN_KEY, ORIGIN_USER

    return tariff is not None and tariff.get(ORIGIN_KEY) == ORIGIN_USER


def _open_tariff_editor(profile_id: str | None, open_tariff: tuple[str, str] | None) -> None:
    """Switch to the Tarife page with this profile and (optionally) a user tariff opened."""
    from ui.navigation import switch_to_page
    from ui.pages.page_tariffs import request_tariff_page

    request_tariff_page(profile_id, open_tariff)
    switch_to_page(_TARIFFS_PAGE_URL)


def _next_month_in_planning_tz() -> tuple[int, int]:
    from house_config.tariff_month_hints import next_calendar_month

    now = _planning_now_for_tariffs()
    return next_calendar_month(now.year, now.month)


def _render_next_month_rate_entry(
    *,
    tariff: dict,
    side: str,
    year: int,
    month: int,
    session_scope: str,
    profile_id: str | None,
) -> None:
    """Warn when the next calendar month is missing on a monthly_table tariff.

    Catalog tariffs get the inline form (writes the site copy of tariffs.json, until P8);
    user tariffs are edited in the Tarife page's editor (P7 D6), where their rate table lives.
    """
    from house_config.tariff_month_hints import monthly_rates_cover_month

    if str(tariff.get("type", "")).strip().lower() != "monthly_table":
        return
    if monthly_rates_cover_month(tariff, year, month):
        return

    side_label = "Bezug" if side == "import" else "Einspeise"
    tariff_label = str(tariff.get("label") or tariff.get("id") or side)
    if _is_user_tariff(tariff):
        st.warning(
            f"Benutzertarif „{tariff_label}“ ({side_label}) hat keinen Eintrag für "
            f"{year}-{month:02d} (nächster Monat). Bis zur Aktualisierung wird temporär "
            "der Vorjahres- bzw. Vormonatswert verwendet. Den Monatspreis im "
            "Tarif-Editor eintragen."
        )
        if st.button(
            "Im Tarif-Editor öffnen",
            key=scoped_widget_key(session_scope, f"next_month_editor_{side}"),
        ):
            _open_tariff_editor(profile_id, (side, str(tariff["id"])))
        return
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
    from house_config.tariffs_store import ensure_user_fixed_option

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
    return (
        ensure_user_fixed_option(filtered_imports),
        ensure_user_fixed_option(filtered_exports),
    )


def _render_user_fixed_import_cent(
    *,
    container,
    session_scope: str,
    scenario_settings: dict,
) -> None:
    from house_config.tariffs_store import USER_IMPORT_CENT_KEY

    imp_cent_key = scoped_widget_key(session_scope, "scenario_user_import_cent")
    if imp_cent_key not in st.session_state:
        saved = scenario_settings.get(USER_IMPORT_CENT_KEY)
        st.session_state[imp_cent_key] = (
            float(saved) if saved is not None else 20.0
        )
    container.number_input(
        "Bezugspreis (Cent/kWh)",
        min_value=0.01,
        step=0.1,
        format="%.2f",
        key=imp_cent_key,
        help=(
            "Lieferanten-Arbeitspreis inkl. USt. "
            "Netznutzung Arbeitspreis kommt aus dem Hausprofil."
        ),
    )
    container.caption(
        "Lieferanten-Arbeitspreis inkl. USt; Netznutzung aus dem Hausprofil."
    )


def _render_user_fixed_export_cent(
    *,
    container,
    session_scope: str,
    scenario_settings: dict,
) -> None:
    from house_config.tariffs_store import USER_EXPORT_CENT_KEY

    exp_cent_key = scoped_widget_key(session_scope, "scenario_user_export_cent")
    if exp_cent_key not in st.session_state:
        saved = scenario_settings.get(USER_EXPORT_CENT_KEY)
        st.session_state[exp_cent_key] = (
            float(saved) if saved is not None else 0.0
        )
    container.number_input(
        "Einspeisevergütung (Cent/kWh)",
        min_value=0.0,
        step=0.1,
        format="%.2f",
        key=exp_cent_key,
    )


def _render_scenario_tariff_picks(
    ctx: dict,
    filtered_imports: list,
    filtered_exports: list,
    current_import_id: str | None,
    current_export_id: str | None,
) -> tuple[object, object]:
    from house_config.tariffs_store import is_user_fixed_tariff_id

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
    selected_import = lookup_entity_id(ctx["imp_map"], imp_pick)
    selected_export = lookup_entity_id(ctx["exp_map"], exp_pick)
    scenario_settings = ctx["scenario_template"].get("settings") or {}
    if is_user_fixed_tariff_id(selected_import):
        _render_user_fixed_import_cent(
            container=import_pick_col,
            session_scope=session_scope,
            scenario_settings=scenario_settings,
        )
    if is_user_fixed_tariff_id(selected_export):
        _render_user_fixed_export_cent(
            container=export_pick_col,
            session_scope=session_scope,
            scenario_settings=scenario_settings,
        )
    return imp_pick, exp_pick


def _render_edibert_preview(
    ctx: dict,
    picks: dict,
    tariff: dict,
    *,
    direction: str,
    title: str,
) -> None:
    """Edibert's hints and price curves of the selected tariff for the scenario's house profile."""
    from edibert.ui.embed import render_preview

    from house_config.edibert_tariffs import (
        cached_tariff_set,
        host_house_for_profile,
        tariff_by_id,
    )
    from runtime_store.persist_paths import (
        resolve_grid_fees_json_path,
        resolve_tariffs_json_path,
    )

    st.caption(title)
    profile_id = picks["selected_profile_id"]
    if not profile_id:
        st.caption("Vorschau erst mit gewähltem Hausprofil (Land, Region, Netzbereich).")
        return
    try:
        house = host_house_for_profile(
            profile_id, picks["selected_profile"], resolve_grid_fees_json_path()
        )
        edibert_tariff = tariff_by_id(
            cached_tariff_set(resolve_tariffs_json_path()), direction, str(tariff["id"])
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    prefix = scoped_widget_key(ctx["session_scope"], f"tariff_preview_{direction}") + "."
    render_preview(edibert_tariff, house, language="de", key_prefix=prefix)


def _render_scenario_tariff_previews(
    ctx: dict,
    picks: dict,
    selected_import: str | None,
    selected_export: str | None,
) -> tuple[dict | None, dict | None]:
    from house_config.tariffs_store import is_user_fixed_tariff_id

    import_tariff = None
    export_tariff = None
    _, import_param_col, export_param_col = st.columns(3)
    if selected_import and not is_user_fixed_tariff_id(selected_import):
        import_tariff = next(t for t in ctx["import_tariffs"] if t["id"] == selected_import)
        with import_param_col:
            _render_edibert_preview(
                ctx, picks, import_tariff, direction="import", title="Bezugstarif-Vorschau"
            )
    if selected_export and not is_user_fixed_tariff_id(selected_export):
        export_tariff = next(t for t in ctx["export_tariffs"] if t["id"] == selected_export)
        with export_param_col:
            _render_edibert_preview(
                ctx, picks, export_tariff, direction="export", title="Einspeisetarif-Vorschau"
            )
    return import_tariff, export_tariff


def _scenario_form_dirty(ctx: dict) -> bool:
    from ui.pages.scenario_editor_session import _active_scenario_form_is_dirty

    return _active_scenario_form_is_dirty(
        ctx["selected"],
        profiles=ctx["profiles"],
        batteries=ctx["batteries"],
        pv_systems=ctx["pv_systems"],
        import_tariffs=ctx["import_tariffs"],
        export_tariffs=ctx["export_tariffs"],
    )


def _render_tariff_editor_links(
    ctx: dict,
    picks: dict,
    import_tariff: dict | None,
    export_tariff: dict | None,
) -> None:
    """Buttons to the Tarife page: manage user tariffs, or edit the selected user tariff."""
    session_scope = ctx["session_scope"]
    profile_id = picks["selected_profile_id"]
    dirty = _scenario_form_dirty(ctx)
    help_text = (
        "Zuerst das Szenario speichern; ungespeicherte Änderungen gingen beim Seitenwechsel verloren."
        if dirty
        else "Öffnet die Seite Tarife (eingebetteter Tarif-Editor) mit dem Hausprofil dieses Szenarios."
    )
    manage_col, import_col, export_col = st.columns(3)
    if manage_col.button(
        "Benutzertarife verwalten",
        key=scoped_widget_key(session_scope, "tariff_editor_manage"),
        disabled=dirty,
        help=help_text,
    ):
        _open_tariff_editor(profile_id, None)
    for tariff, direction, col in (
        (import_tariff, "import", import_col),
        (export_tariff, "export", export_col),
    ):
        if not _is_user_tariff(tariff):
            continue
        if col.button(
            "Benutzertarif bearbeiten",
            key=scoped_widget_key(session_scope, f"tariff_editor_edit_{direction}"),
            disabled=dirty,
            help=help_text,
        ):
            _open_tariff_editor(profile_id, (direction, str(tariff["id"])))


def _render_scenario_next_month_rates(
    ctx: dict,
    picks: dict,
    import_tariff: dict | None,
    export_tariff: dict | None,
) -> None:
    from house_config.tariff_month_hints import is_within_days_of_next_month

    if not is_within_days_of_next_month(_planning_now_for_tariffs(), days=2):
        return
    next_y, next_m = _next_month_in_planning_tz()
    if import_tariff is not None:
        _render_next_month_rate_entry(
            tariff=import_tariff,
            side="import",
            year=next_y,
            month=next_m,
            session_scope=ctx["session_scope"],
            profile_id=picks["selected_profile_id"],
        )
    if export_tariff is not None:
        _render_next_month_rate_entry(
            tariff=export_tariff,
            side="export",
            year=next_y,
            month=next_m,
            session_scope=ctx["session_scope"],
            profile_id=picks["selected_profile_id"],
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


def _user_fixed_cents_from_session(
    session_scope: str,
    import_tariff_id: str | None,
    export_tariff_id: str | None,
) -> tuple[float | None, float | None]:
    from house_config.tariffs_store import is_user_fixed_tariff_id

    user_import_cent = None
    user_export_cent = None
    if is_user_fixed_tariff_id(import_tariff_id):
        raw_imp = st.session_state.get(
            scoped_widget_key(session_scope, "scenario_user_import_cent")
        )
        if raw_imp is not None:
            user_import_cent = float(raw_imp)
    if is_user_fixed_tariff_id(export_tariff_id):
        raw_exp = st.session_state.get(
            scoped_widget_key(session_scope, "scenario_user_export_cent")
        )
        if raw_exp is not None:
            user_export_cent = float(raw_exp)
    return user_import_cent, user_export_cent


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
        ctx, picks, selected_import, selected_export
    )
    _render_tariff_editor_links(ctx, picks, import_tariff, export_tariff)
    _render_scenario_next_month_rates(ctx, picks, import_tariff, export_tariff)
    _render_tariff_catalog_notice(selected_import, selected_export)
    return {"imp_pick": imp_pick, "exp_pick": exp_pick}
