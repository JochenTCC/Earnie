"""Wallboxen-Tab im Hauskonfigurator (multi-EV M1b, components.json ``wallboxes[]``)."""
from __future__ import annotations

import os

import streamlit as st

from house_config.label_uniqueness import allocate_unique_label
from house_config.wallboxes import pair_limits
from runtime_store.persist_paths import resolve_components_json_path
from ui.auto_persist import (
    auto_persist,
    persisted_state_known,
    require_saved,
    seed_persisted,
    warn_not_saved,
)
from ui.flash import flash
from ui.form_layout import labeled_number_input, labeled_selectbox, labeled_text_input
from ui.house_config_wallbox_io import delete_wallbox, upsert_wallbox, wallboxes_map
from ui.label_select import (
    NEW_OPTION,
    align_label_select_session,
    label_select_choices,
    resolve_label_select,
)

SELECT_KEY = "planning_wb_select"
_SESSION_SYNC_KEY = "planning_wb_sync_id"
_SESSION_FILE_STAMP_KEY = "planning_wb_file_stamp"
_SESSION_SELECT_PENDING_KEY = "planning_wb_select_pending"
_SESSION_SELECTED_ID_KEY = "planning_wb_selected_id"

# Defaults of a new wallbox: 3 phases, 6–16 A at 230 V (11 kW).
DEFAULT_WALLBOX = {
    "voltage_v": 230.0,
    "phases": 3,
    "min_current_a": 6.0,
    "max_current_a": 16.0,
}


def _scoped_key(session_scope: str, base: str) -> str:
    return f"{session_scope}__{base}"


def _file_stamp() -> str:
    path = resolve_components_json_path()
    try:
        return f"{os.path.abspath(path)}:{os.path.getmtime(path)}"
    except OSError:
        return os.path.abspath(path)


def _clear_scoped_widget_keys(session_scope: str) -> None:
    prefix = f"{session_scope}__"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            del st.session_state[key]


def _seed_widgets(session_scope: str, existing: dict, wallboxes: dict[str, dict]) -> None:
    source = existing or {
        "label": allocate_unique_label("Wallbox", list(wallboxes.values())),
        **DEFAULT_WALLBOX,
    }
    st.session_state[_scoped_key(session_scope, "planning_wb_label")] = str(source["label"])
    st.session_state[_scoped_key(session_scope, "planning_wb_voltage")] = float(source["voltage_v"])
    st.session_state[_scoped_key(session_scope, "planning_wb_phases")] = int(source["phases"])
    st.session_state[_scoped_key(session_scope, "planning_wb_min_a")] = float(source["min_current_a"])
    st.session_state[_scoped_key(session_scope, "planning_wb_max_a")] = float(source["max_current_a"])


def _sync_session(session_scope: str, existing: dict, wallboxes: dict[str, dict]) -> None:
    stamp = _file_stamp()
    if (
        st.session_state.get(_SESSION_SYNC_KEY) != session_scope
        or st.session_state.get(_SESSION_FILE_STAMP_KEY) != stamp
        or _scoped_key(session_scope, "planning_wb_label") not in st.session_state
    ):
        _clear_scoped_widget_keys(session_scope)
        _seed_widgets(session_scope, existing, wallboxes)
        st.session_state[_SESSION_SYNC_KEY] = session_scope
        st.session_state[_SESSION_FILE_STAMP_KEY] = stamp


def _render_select(wallboxes: dict[str, dict]) -> tuple[str, bool]:
    pending = st.session_state.pop(_SESSION_SELECT_PENDING_KEY, None)
    if pending is not None:
        st.session_state[SELECT_KEY] = pending
    ids = list(wallboxes)
    options, id_by_display = label_select_choices(wallboxes, ids)
    align_label_select_session(
        select_key=SELECT_KEY,
        selected_id_key=_SESSION_SELECTED_ID_KEY,
        entity_map=wallboxes,
        entity_ids=ids,
        id_by_display=id_by_display,
    )
    if SELECT_KEY not in st.session_state:
        # Prefer an existing wallbox on first open — never land on — neu — unasked.
        st.session_state[SELECT_KEY] = options[1] if ids else options[0]
    selected = resolve_label_select(
        labeled_selectbox("Wallbox", options=options, key=SELECT_KEY), id_by_display
    )
    is_new = selected == NEW_OPTION
    if not is_new:
        st.session_state[_SESSION_SELECTED_ID_KEY] = selected
    return ("" if is_new else str(selected)), is_new


def _render_fields(session_scope: str) -> dict:
    label = labeled_text_input("Bezeichnung", key=_scoped_key(session_scope, "planning_wb_label"))
    voltage = labeled_number_input(
        "Spannung (V)",
        min_value=100.0,
        max_value=500.0,
        step=1.0,
        key=_scoped_key(session_scope, "planning_wb_voltage"),
        help="Spannung je Phase. Standard: 230 V.",
    )
    phases = labeled_number_input(
        "Phasen",
        min_value=1,
        max_value=3,
        step=1,
        key=_scoped_key(session_scope, "planning_wb_phases"),
        help="Phasen, mit denen die Wallbox laden kann.",
    )
    min_a = labeled_number_input(
        "Mindest-Ladestrom (A)",
        min_value=0.0,
        step=1.0,
        key=_scoped_key(session_scope, "planning_wb_min_a"),
    )
    max_a = labeled_number_input(
        "Höchst-Ladestrom (A)",
        min_value=0.0,
        step=1.0,
        key=_scoped_key(session_scope, "planning_wb_max_a"),
    )
    fields = {
        "label": str(label or "").strip(),
        "voltage_v": float(voltage),
        "phases": int(phases),
        "min_current_a": float(min_a),
        "max_current_a": float(max_a),
    }
    kw = fields["voltage_v"] * fields["phases"] / 1000.0
    st.caption(
        f"Ladeleistung der Wallbox: {fields['min_current_a'] * kw:.2f} – "
        f"{fields['max_current_a'] * kw:.2f} kW (Strom × Spannung × Phasen). "
        "Am E-Auto gilt der gemeinsame Bereich von Auto und Wallbox."
    )
    return fields


def _blockers(fields: dict) -> list[str]:
    out: list[str] = []
    if not fields["label"]:
        out.append("Bezeichnung")
    if fields["min_current_a"] > fields["max_current_a"]:
        out.append("Mindest-Ladestrom größer als Höchst-Ladestrom")
    return out


def _save(fields: dict, *, stable_id: str) -> str | None:
    try:
        persisted = upsert_wallbox(fields, stable_id=stable_id)
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.session_state[_SESSION_FILE_STAMP_KEY] = _file_stamp()
    if not stable_id:
        st.session_state[_SESSION_SELECT_PENDING_KEY] = persisted
        st.session_state[_SESSION_SYNC_KEY] = None
    return persisted


def _render_delete(stable_id: str, wallboxes: dict[str, dict]) -> None:
    if not st.button("Wallbox entfernen", key="planning_wb_delete"):
        return
    try:
        delete_wallbox(stable_id)
    except ValueError as exc:
        st.error(str(exc))
        return
    remaining = [wid for wid in wallboxes if wid != stable_id]
    _clear_scoped_widget_keys(stable_id)
    _clear_scoped_widget_keys("__new__")
    st.session_state.pop(_SESSION_SELECTED_ID_KEY, None)
    st.session_state.pop(f"_auto_persist_fp::planning_wb::{stable_id}", None)
    st.session_state[_SESSION_SELECT_PENDING_KEY] = remaining[0] if remaining else NEW_OPTION
    st.session_state[_SESSION_SYNC_KEY] = None
    flash("success", "Wallbox entfernt.")
    st.rerun()


def _render_assigned_evs(stable_id: str, fields: dict) -> None:
    """EVs at this wallbox with the charge range of each pair."""
    from house_config.wallboxes import evs_at_wallbox, normalize_ev_current_fields
    from ui.house_config_wallbox_io import raw_house_document

    users = evs_at_wallbox(raw_house_document(), stable_id)
    if not users:
        st.caption("Keinem E-Auto zugeordnet (Zuordnung im Hausprofil beim E-Auto).")
        return
    wallbox = {"id": stable_id, **fields}
    for profile_id, ev in users:
        name = f"{ev.get('label') or ev.get('id')} (Hausprofil {profile_id})"
        try:
            limits = pair_limits(
                normalize_ev_current_fields(ev, label=name), wallbox, label=name
            )
        except ValueError as exc:
            st.error(str(exc))
            continue
        st.caption(
            f"E-Auto {name}: {limits['min_current_a']:g}–{limits['max_current_a']:g} A, "
            f"{limits['phases']} Phase(n) → {limits['min_power_kw']:.2f} – "
            f"{limits['max_power_kw']:.2f} kW"
        )


def render_wallbox_planning_tab() -> None:
    st.caption(
        "Wallboxen sind Anlagenteile wie Batterien und Wechselrichter. Das E-Auto im "
        "Hausprofil wird einer Wallbox fest zugeordnet; geladen wird im gemeinsamen Bereich "
        "von Auto und Wallbox. Lade-Bindings `evcs.<Kennung>.*` unter "
        "**Daemon Control → EHAL-Com**."
    )
    wallboxes = wallboxes_map()
    stable_id, is_new = _render_select(wallboxes)
    existing = wallboxes.get(stable_id, {})
    session_scope = "__new__" if is_new else stable_id
    _sync_session(session_scope, existing, wallboxes)
    if not is_new:
        st.caption(f"Kennung: `{stable_id}` (fest, die E-Autos verweisen darauf)")
    fields = _render_fields(session_scope)
    blockers = _blockers(fields)
    if blockers:
        warn_not_saved("Wallbox", blockers)
    persist_key = f"planning_wb::{stable_id or '__new__'}"
    payload = {"id": stable_id, **fields}
    if (
        existing
        and not persisted_state_known(persist_key)
        and all(existing.get(k) == v for k, v in fields.items())
    ):
        # First render of a stored wallbox: nothing to write until a real edit.
        seed_persisted(persist_key, payload)
    wrote = auto_persist(
        state_key=persist_key,
        payload=payload,
        save=lambda: require_saved(_save(fields, stable_id=stable_id)),
        ready=not blockers,
    )
    if wrote:
        st.rerun()
    if not is_new:
        _render_assigned_evs(stable_id, fields)
        _render_delete(stable_id, wallboxes)
