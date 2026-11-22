"""Scenario editor overview: one row per scenario (docs/dev/scenario-editor-usability.md).

The row opens the scenario in the form below, carries its position and is the only writer of
``enabled`` („Aktiv im Explorer“). Widgets only queue a request in their callback; the writes
run at the top of the next script run (``apply_pending_overview_writes``), before the
catalogs are loaded, so the page renders what the file holds.
"""
from __future__ import annotations

import streamlit as st

from runtime_store.shadow.errors import ConfigReadOnlyError
from ui.auto_persist import SHADOW_READONLY_CAPTION
from ui.scenario_form_helpers import (
    NEW_SCENARIO_OPTION,
    backtesting_scenarios_file_stamp,
    entity_human_label,
    missing_scenario_refs,
)

OVERVIEW_KEY = "scenario_overview"
OPEN_KEY_PREFIX = "scenario_open__"
ACTIVE_KEY_PREFIX = "scenario_active__"
POSITION_KEY_PREFIX = "scenario_pos__"
DUPLICATE_KEY = "scenario_duplicate"
NEW_EMPTY_KEY = "scenario_new_empty"
# Scenario id a row asked to open (or ``NEW_SCENARIO_OPTION``); read by the selection.
REQUEST_KEY = "scenario_editor_request"
# Template of the next new scenario: a scenario id (duplicate) or ``TEMPLATE_EMPTY``.
TEMPLATE_SOURCE_KEY = "scenario_editor_template_source"
TEMPLATE_EMPTY = "__empty__"
_PENDING_ENABLED_KEY = "scenario_overview_pending_enabled"
_PENDING_POSITION_KEY = "scenario_overview_pending_position"
_ERROR_KEY = "scenario_overview_error"
# Same key as the scenario editor's file stamp: a write here must not reseed the open form.
_SESSION_FILE_STAMP_KEY = "scenario_editor_file_stamp"


def _request_open(scenario_id: str) -> None:
    st.session_state[REQUEST_KEY] = scenario_id


def _request_new(template_source: str) -> None:
    st.session_state[TEMPLATE_SOURCE_KEY] = template_source
    st.session_state[REQUEST_KEY] = NEW_SCENARIO_OPTION


def _queue_enabled(scenario_id: str) -> None:
    st.session_state[_PENDING_ENABLED_KEY] = (
        scenario_id,
        bool(st.session_state[ACTIVE_KEY_PREFIX + scenario_id]),
    )


def _queue_position(scenario_id: str) -> None:
    st.session_state[_PENDING_POSITION_KEY] = (
        scenario_id,
        int(st.session_state[POSITION_KEY_PREFIX + scenario_id]),
    )


def _write(action) -> None:
    try:
        action()
    except ConfigReadOnlyError:
        st.session_state[_ERROR_KEY] = SHADOW_READONLY_CAPTION
        return
    except ValueError as exc:
        st.session_state[_ERROR_KEY] = str(exc)
        return
    st.session_state[_SESSION_FILE_STAMP_KEY] = backtesting_scenarios_file_stamp()


def moved_order(non_live_ids: list[str], scenario_id: str, position: int, *, live_first: bool) -> list[str]:
    """Non-Live ids with ``scenario_id`` at the shown ``position`` (Live is position 1)."""
    rest = [sid for sid in non_live_ids if sid != scenario_id]
    index = position - (2 if live_first else 1)
    index = max(0, min(len(rest), index))
    return [*rest[:index], scenario_id, *rest[index:]]


def apply_pending_overview_writes(live_id: str) -> None:
    """Run the write a row widget queued in the last run (enabled or position)."""
    from ui.house_config_io import (
        load_backtesting_scenarios_raw,
        reorder_scenarios,
        set_scenario_enabled,
    )
    from ui.scenario_form_helpers import ordered_user_scenario_ids

    pending_enabled = st.session_state.pop(_PENDING_ENABLED_KEY, None)
    if pending_enabled is not None:
        scenario_id, enabled = pending_enabled
        _write(lambda: set_scenario_enabled(scenario_id, enabled))
    pending_position = st.session_state.pop(_PENDING_POSITION_KEY, None)
    if pending_position is not None:
        scenario_id, position = pending_position
        ids = ordered_user_scenario_ids(
            [str(s.get("id", "")).strip() for s in load_backtesting_scenarios_raw().get("scenarios", [])],
            live_scenario_id=live_id,
        )
        live_first = bool(live_id) and live_id in ids
        non_live = [sid for sid in ids if sid != live_id]
        order = moved_order(non_live, scenario_id, position, live_first=live_first)
        _write(lambda: reorder_scenarios(order))


def _entity_label(items: list[dict], entity_id: str) -> str:
    if not entity_id:
        return "—"
    item = next((i for i in items if str(i.get("id") or "").strip() == entity_id), None)
    return entity_human_label(item) if item is not None else entity_id


def _row_status(scenario: dict, *, live_id: str, catalogs: dict) -> str:
    if str(scenario.get("id", "")).strip() == live_id:
        return "Live"
    missing = missing_scenario_refs(
        dict(scenario.get("settings") or {}),
        profiles=catalogs["profiles"],
        batteries=catalogs["batteries"],
        pv_systems=catalogs["pv_systems"],
        import_tariffs=catalogs["import_tariffs"],
        export_tariffs=catalogs["export_tariffs"],
    )
    return "Verweis fehlt" if missing else "OK"


_COLUMNS = [0.9, 3.0, 1.6, 2.2, 2.4, 2.4, 1.5]
_HEADERS = ["Pos.", "Bezeichnung", "Aktiv im Explorer", "Hausprofil", "Bezug", "Einspeisung", "Status"]


def _render_row(
    scenario: dict,
    position: int,
    positions: list[int],
    *,
    active: str,
    live_id: str,
    catalogs: dict,
) -> None:
    sid = str(scenario.get("id", "")).strip()
    is_live = sid == live_id
    settings = dict(scenario.get("settings") or {})
    cols = st.columns(_COLUMNS, vertical_alignment="center")
    if is_live or len(positions) < 2:
        cols[0].caption(f"{position} · fest" if is_live else str(position))
    else:
        # Seeded from the file every run (allowed: the widget has not rendered yet).
        st.session_state[POSITION_KEY_PREFIX + sid] = position
        cols[0].selectbox(
            f"Position {scenario.get('label') or sid}",
            options=positions,
            key=POSITION_KEY_PREFIX + sid,
            on_change=_queue_position,
            args=(sid,),
            label_visibility="collapsed",
        )
    cols[1].button(
        str(scenario.get("label") or sid),
        key=OPEN_KEY_PREFIX + sid,
        type="primary" if sid == active else "secondary",
        on_click=_request_open,
        args=(sid,),
        width="stretch",
    )
    st.session_state[ACTIVE_KEY_PREFIX + sid] = is_live or scenario.get("enabled", True) is not False
    cols[2].checkbox(
        "aktiv",
        key=ACTIVE_KEY_PREFIX + sid,
        disabled=is_live,
        on_change=_queue_enabled,
        args=(sid,),
        help=(
            "Das Live-Szenario läuft im Szenario-Explorer immer mit."
            if is_live
            else "Nur aktive Szenarien rechnet der Szenario-Explorer. Wirkt sofort; "
            "vorhandene Explorer-Ergebnisse werden dadurch ungültig."
        ),
    )
    profile_id = str(settings.get("house_profile_id") or "").strip()
    profile = catalogs["profiles"].get(profile_id)
    cols[3].write(entity_human_label(profile) if profile else (profile_id or "—"))
    cols[4].write(
        _entity_label(catalogs["import_tariffs"], str(settings.get("import_tariff_id") or "").strip())
    )
    cols[5].write(
        _entity_label(catalogs["export_tariffs"], str(settings.get("export_tariff_id") or "").strip())
    )
    cols[6].write(_row_status(scenario, live_id=live_id, catalogs=catalogs))


def render_scenario_overview(
    *,
    scenario_ids: list[str],
    active: str,
    live_id: str,
    catalogs: dict,
    allow_new: bool,
) -> None:
    """Overview table plus „Duplizieren“ / „Neu (leer)“; marks the open scenario."""
    by_id = {str(s.get("id", "")).strip(): s for s in catalogs["scenarios"]}
    rows = [by_id[sid] for sid in scenario_ids if sid in by_id]
    with st.container(key=OVERVIEW_KEY):
        head_col, count_col = st.columns([3, 2], vertical_alignment="center")
        head_col.subheader("Szenarien")
        enabled_count = sum(
            1
            for s in rows
            if str(s.get("id", "")).strip() == live_id or s.get("enabled", True) is not False
        )
        count_col.caption(f"{enabled_count} von {len(rows)} im Szenario-Explorer aktiv")
        error = st.session_state.pop(_ERROR_KEY, None)
        if error:
            st.error(error)
        header = st.columns(_COLUMNS)
        for col, text in zip(header, _HEADERS):
            col.caption(f"**{text}**")
        live_first = bool(live_id) and live_id in by_id
        first_movable = 2 if live_first else 1
        positions = list(range(first_movable, len(rows) + 1))
        for position, scenario in enumerate(rows, start=1):
            _render_row(
                scenario,
                position,
                positions,
                active=active,
                live_id=live_id,
                catalogs=catalogs,
            )
        st.caption(
            "Klick auf eine Bezeichnung öffnet das Szenario unten. Live steht immer oben "
            "und läuft im Szenario-Explorer immer mit."
        )
        if allow_new:
            dup_col, new_col, _rest = st.columns([2, 2, 3])
            source = active if active in by_id else live_id
            source_label = str((by_id.get(source) or {}).get("label") or source)
            dup_col.button(
                f"„{source_label}“ duplizieren",
                key=DUPLICATE_KEY,
                on_click=_request_new,
                args=(source,),
                disabled=source not in by_id,
                width="stretch",
            )
            new_col.button(
                "Neu (leer)",
                key=NEW_EMPTY_KEY,
                on_click=_request_new,
                args=(TEMPLATE_EMPTY,),
                width="stretch",
            )
