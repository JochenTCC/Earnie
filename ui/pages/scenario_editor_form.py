"""Scenario editor form/tab rendering."""
from __future__ import annotations

import streamlit as st

import config
from ui.form_layout import form_group
from ui.pages.scenario_editor_sections import (
    _persist_or_delete_scenario,
    _prepare_scenario_tab,
    _render_scenario_entity_picks,
    _render_scenario_identity_fields,
    _render_scenario_import_cap,
)
from ui.pages.scenario_editor_tariffs import (
    _next_month_in_planning_tz,
    _render_next_month_rate_entry,
    _render_scenario_tariff_block,
)
from ui.scenario_form_helpers import scoped_widget_key


# Form groups (docs/dev/scenario-editor-usability.md § D); stable keys keep the open state.
GROUP_KEYS = {
    "label": "scenario_group_label",
    "components": "scenario_group_components",
    "tariffs": "scenario_group_tariffs",
    "import_cap": "scenario_group_import_cap",
}


def _form_heading(ctx: dict) -> str:
    if ctx["is_new"]:
        return "Neues Szenario"
    existing = ctx["existing"] or {}
    return str(existing.get("label") or ctx["stable_scenario_id"])


def _import_cap_status(ctx: dict) -> str:
    cap = st.session_state.get(scoped_widget_key(ctx["session_scope"], "scenario_import_cap"))
    return "keine Grenze" if cap is None else f"{float(cap):.2f} kW".replace(".", ",")


def _render_scenarios_tab() -> None:
    live_id = config.get_live_scenario_id()
    st.caption(
        "Live-Szenario ist die Baseline für Szenario-Explorer "
        "und Echtzeit-Betrieb. Standort und Zeitzone kommen aus dem Hausprofil."
    )
    ctx = _prepare_scenario_tab(live_id)
    st.divider()
    st.subheader(_form_heading(ctx))
    with form_group("Bezeichnung", key=GROUP_KEYS["label"], expanded=True):
        label = _render_scenario_identity_fields(ctx)
    with form_group("Komponenten", key=GROUP_KEYS["components"], expanded=True):
        picks = _render_scenario_entity_picks(ctx)
    with form_group("Tarife", key=GROUP_KEYS["tariffs"], expanded=True):
        tariffs = _render_scenario_tariff_block(ctx, picks)
    with form_group(
        "Bezugsgrenze / Leistungspreis",
        key=GROUP_KEYS["import_cap"],
        status=_import_cap_status(ctx),
    ):
        import_cap_errors = _render_scenario_import_cap(ctx, picks)
    _persist_or_delete_scenario(ctx, label, picks, tariffs, import_cap_errors)
