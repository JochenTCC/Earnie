"""Scenario editor form/tab rendering."""
from __future__ import annotations

import streamlit as st

import config
from ui.house_config_io import reorder_scenarios
from ui.pages.page_scenario_editor import (
    _SESSION_FILE_STAMP_KEY,
    _SESSION_SELECT_PENDING_KEY,
)
from ui.pages.scenario_editor_sections import (
    _next_month_in_planning_tz,
    _persist_or_delete_scenario,
    _prepare_scenario_tab,
    _render_next_month_rate_entry,
    _render_scenario_entity_picks,
    _render_scenario_identity_fields,
    _render_scenario_tariff_block,
)
from ui.scenario_form_helpers import (
    NEW_SCENARIO_OPTION,
    backtesting_scenarios_file_stamp,
)


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
    ctx = _prepare_scenario_tab(live_id)
    label = _render_scenario_identity_fields(ctx)
    picks = _render_scenario_entity_picks(ctx)
    tariffs = _render_scenario_tariff_block(ctx, picks)
    _persist_or_delete_scenario(ctx, label, picks, tariffs)
