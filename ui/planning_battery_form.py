"""Batterie-Tab im Hauskonfigurator.

State/session helpers live in ``ui.planning_battery_state`` and the field renderers
in ``ui.planning_battery_fields``; the names callers and tests use stay importable here.
"""
from __future__ import annotations

import streamlit as st

from house_config.battery_control import DEFAULT_BATTERY_CONTROL
from house_config.entity_id_lock import ID_PROVISIONAL_LABEL_KEY
from house_config.id_slug import slug_id
from house_config.powerstation import BACKING_VIRTUAL
from house_config.topology_regulates import REGULATES_ON_GRID
from ui.flash import flash
from ui.house_config_io import (
    delete_battery,
    get_live_scenario_refs,
    list_batteries,
    upsert_battery,
)
from ui.planning_battery_inverter import (
    persist_builtin_inverter,
    render_ecoflow_preset_button,
)
from ui.auto_persist import auto_persist, payload_fingerprint, require_saved
from ui.form_layout import labeled_selectbox
from ui.label_select import (
    NEW_OPTION,
    align_label_select_session,
    label_select_choices,
    resolve_label_select,
)
from ui.planning_battery_fields import _render_battery_fields
from ui.planning_battery_state import (  # noqa: F401 — re-exports used by tests
    _SESSION_FILE_STAMP_KEY,
    _SESSION_PROVISIONAL_LABEL_KEY,
    _SESSION_SELECT_PENDING_KEY,
    _SESSION_SELECTED_ID_KEY,
    _SESSION_SUPPRESS_AUTOPERSIST_KEY,
    _SESSION_SYNC_KEY,
    _SESSION_TEMPLATE_SOURCE_KEY,
    _apply_pending_battery_select,
    _battery_session_scope,
    _battery_widget_state_missing,
    _clear_scoped_widget_keys,
    _config_file_stamp,
    _remember_battery_template_source,
    _scoped_key,
    _seed_battery_widget_state,
    _sync_battery_session,
    new_battery_template,
)


def _initial_battery_index(battery_ids: list[str]) -> int | None:
    if "planning_battery_select" in st.session_state:
        return None
    battery_id = str(get_live_scenario_refs().get("battery_id", "") or "").strip()
    if battery_id in battery_ids:
        return battery_ids.index(battery_id) + 1
    return None


def _battery_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in list_batteries()}


def _battery_selectbox(options: list[str], initial_index: int | None) -> str:
    if initial_index is not None:
        return labeled_selectbox(
            "Batterie",
            options=options,
            index=initial_index,
            key="planning_battery_select",
        )
    return labeled_selectbox(
        "Batterie",
        options=options,
        key="planning_battery_select",
    )


def _resolve_battery_existing(
    selected: str,
    battery_map: dict[str, dict],
    *,
    is_new: bool,
) -> dict:
    if is_new:
        source_id = str(st.session_state.get(_SESSION_TEMPLATE_SOURCE_KEY) or "")
        return new_battery_template(
            list_batteries(),
            source_id=source_id,
            live_battery_id=str(
                get_live_scenario_refs().get("battery_id", "") or ""
            ),
        )
    _remember_battery_template_source(selected)
    st.session_state[_SESSION_SELECTED_ID_KEY] = selected
    return battery_map.get(selected, {})


def _render_battery_select() -> dict:
    """Battery selectbox plus session reseed; returns the editor context."""
    _apply_pending_battery_select()
    battery_map = _battery_by_id()
    battery_ids = sorted(battery_map.keys())
    options, id_by_display = label_select_choices(battery_map, battery_ids)
    align_label_select_session(
        select_key="planning_battery_select",
        selected_id_key=_SESSION_SELECTED_ID_KEY,
        entity_map=battery_map,
        entity_ids=battery_ids,
        id_by_display=id_by_display,
    )
    initial_index = _initial_battery_index(battery_ids)
    selected_display = _battery_selectbox(options, initial_index)
    selected = resolve_label_select(selected_display, id_by_display)
    is_new = selected == NEW_OPTION
    existing = _resolve_battery_existing(selected, battery_map, is_new=is_new)
    session_scope = _battery_session_scope(selected, is_new=is_new)
    file_stamp = _config_file_stamp()
    _sync_battery_session(session_scope, existing, file_stamp=file_stamp)
    return {
        "battery_ids": battery_ids,
        "is_new": is_new,
        "existing": existing,
        "session_scope": session_scope,
    }
























def _battery_save_payload(fields: dict) -> dict:
    payload = {
        "label": fields["label"],
        "type": fields.get("type") or "house",
        "battery_capacity_kwh": fields["capacity"],
        "battery_max_charge_power_kw": fields["max_charge"],
        "battery_max_discharge_power_kw": fields["max_discharge"],
        "battery_efficiency": fields["efficiency"],
        "battery_min_soc": fields["min_soc"],
        "battery_max_soc": fields["max_soc"],
        "threshold_power": fields["threshold_percent"] / 100.0,
        "standby_power_kw": float(fields["standby_power"] or 0.0),
        "control": fields.get("control") or DEFAULT_BATTERY_CONTROL,
        "limits_from_live": bool(fields.get("limits_from_live", False)),
        "ehal_bindings": dict(fields.get("ehal_bindings") or {}),
        "battery_wear": fields["battery_wear"],
    }
    if str(payload.get("type") or "house") == "house":
        payload["regulates_on"] = (
            str(fields.get("regulates_on") or REGULATES_ON_GRID).strip().lower()
            or REGULATES_ON_GRID
        )
    inv_id = str(fields.get("inverter_id") or "").strip()
    if inv_id:
        payload["inverter_id"] = inv_id
    provisional = str(
        fields.get(ID_PROVISIONAL_LABEL_KEY)
        or st.session_state.get(_SESSION_PROVISIONAL_LABEL_KEY)
        or ""
    ).strip()
    if provisional:
        payload[ID_PROVISIONAL_LABEL_KEY] = provisional
    if payload["type"] == "powerstation":
        payload["backing"] = fields.get("backing") or "virtual"
        payload["role"] = fields.get("role") or "single_use"
        attached_ids = [
            str(cid).strip()
            for cid in (fields.get("attached_consumer_ids") or [])
            if str(cid or "").strip()
        ]
        if not attached_ids:
            singular = str(fields.get("attached_consumer_id") or "").strip()
            if singular:
                attached_ids = [singular]
        payload["attached_consumer_ids"] = attached_ids
        payload["attached_consumer_id"] = attached_ids[0] if attached_ids else ""
        if str(payload.get("backing") or "") == BACKING_VIRTUAL:
            payload.pop("inverter_id", None)
    return payload


def _save_battery(
    fields: dict,
    *,
    stable_id: str,
    is_new: bool,
    force_id_from_label: bool = False,
) -> str | None:
    try:
        persisted_id = upsert_battery(
            _battery_save_payload(fields),
            stable_id=stable_id,
            force_id_from_label=force_id_from_label,
        )
        builtin = fields.get("builtin_inverter")
        if builtin and persisted_id:
            payload = dict(builtin)
            payload["owned_by"] = persisted_id
            persist_builtin_inverter(payload, battery_id=persisted_id)
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
    if is_new or (stable_id and persisted_id != stable_id):
        st.session_state[_SESSION_SELECT_PENDING_KEY] = persisted_id
        st.session_state[_SESSION_SYNC_KEY] = None
        st.session_state.pop(_SESSION_PROVISIONAL_LABEL_KEY, None)
    return persisted_id


def _persist_battery_form(
    fields: dict,
    *,
    stable_id: str,
    entity_id: str,
    is_new: bool,
    ready: bool,
) -> None:
    payload = {"id": entity_id, **_battery_save_payload(fields)}
    if fields.get("builtin_inverter"):
        payload["builtin_inverter"] = dict(fields["builtin_inverter"])
    persist_key = f"planning_battery::{stable_id or entity_id}"
    suppress = bool(st.session_state.pop(_SESSION_SUPPRESS_AUTOPERSIST_KEY, False))
    if suppress and ready:
        # Mark draft as clean without writing so delete-of-last is not undone.
        st.session_state[f"_auto_persist_fp::{persist_key}"] = payload_fingerprint(
            payload
        )
        wrote = False
    else:
        wrote = auto_persist(
            state_key=persist_key,
            payload=payload,
            save=lambda: require_saved(
                _save_battery(fields, stable_id=stable_id, is_new=is_new)
            ),
            ready=ready,
        )
    if wrote:
        st.rerun()


def _render_battery_id_from_label(stable_id: str, fields: dict) -> None:
    """One-shot: set frozen id from current Bezeichnung (existing ugly ids)."""
    label = str(fields.get("label") or "").strip()
    if not label or not stable_id:
        return
    desired = slug_id(label)
    if desired == stable_id:
        return
    help_txt = (
        f"Aktuelle ID `{stable_id}` → aus Bezeichnung `{desired}` "
        "(EHAL-Slug; danach fest)."
    )
    if st.button(
        "ID aus Bezeichnung übernehmen",
        key="planning_battery_id_from_label",
        help=help_txt,
    ):
        persisted = _save_battery(
            fields,
            stable_id=stable_id,
            is_new=False,
            force_id_from_label=True,
        )
        if persisted:
            flash("success", f"ID gesetzt: `{persisted}`")
            st.rerun()


def _render_battery_delete(stable_id: str) -> None:
    if not st.button("Batterie entfernen", key="planning_battery_delete"):
        return
    try:
        delete_battery(stable_id)
    except ValueError as exc:
        st.error(str(exc))
        return
    remaining_ids = sorted(_battery_by_id().keys())
    fallback = remaining_ids[0] if remaining_ids else NEW_OPTION
    _clear_scoped_widget_keys(stable_id)
    _clear_scoped_widget_keys("__new__")
    st.session_state.pop(_SESSION_SELECTED_ID_KEY, None)
    st.session_state.pop(f"_auto_persist_fp::planning_battery::{stable_id}", None)
    st.session_state[_SESSION_SELECT_PENDING_KEY] = fallback
    st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
    st.session_state[_SESSION_SYNC_KEY] = None
    if fallback == NEW_OPTION:
        st.session_state[_SESSION_SUPPRESS_AUTOPERSIST_KEY] = True
    flash("success", "Batterie entfernt.")
    st.rerun()


def render_battery_planning_tab() -> None:
    st.caption(
        "Nicht optional, da ansonsten identisch mit Nicht optimierter Referenz."
    )
    ctx = _render_battery_select()
    is_new = ctx["is_new"]
    if render_ecoflow_preset_button(is_new=is_new):
        return
    stable_id = "" if is_new else str(ctx["existing"].get("id", ""))
    fields = _render_battery_fields(
        ctx["session_scope"],
        exclude_id=stable_id,
        battery_id=stable_id,
    )
    label = fields["label"]
    bat_type = str(fields.get("type") or "house").strip().lower()
    backing = str(fields.get("backing") or BACKING_VIRTUAL).strip().lower()
    needs_inv = not (bat_type == "powerstation" and backing == BACKING_VIRTUAL)
    inv_ok = (not needs_inv) or bool(str(fields.get("inverter_id") or "").strip()) or (
        bat_type == "powerstation" and backing != BACKING_VIRTUAL
    )
    ready = (
        bool(str(label or "").strip())
        and float(fields["capacity"] or 0) > 0
        and inv_ok
    )
    if not ready:
        blockers: list[str] = []
        if not str(label or "").strip():
            blockers.append("Bezeichnung")
        if float(fields["capacity"] or 0) <= 0:
            blockers.append("Kapazität > 0")
        if needs_inv and not inv_ok:
            blockers.append("Wechselrichter wählen (Tab Wechselrichter zuerst anlegen)")
        st.warning(
            "Batterie noch nicht gespeichert: "
            + (", ".join(blockers) if blockers else "Formular unvollständig")
            + ". Beim Verlassen des Tabs geht der Entwurf verloren."
        )
    taken = {bid for bid in ctx["battery_ids"] if bid != stable_id}
    entity_id = stable_id.strip() or slug_id(label or "batterie", existing=taken)
    _persist_battery_form(
        fields,
        stable_id=stable_id,
        entity_id=entity_id,
        is_new=is_new,
        ready=ready,
    )
    if not is_new and stable_id:
        _render_battery_id_from_label(stable_id, fields)
        _render_battery_delete(stable_id)
