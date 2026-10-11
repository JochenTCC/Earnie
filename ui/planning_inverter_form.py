"""Wechselrichter-Tab im Hauskonfigurator (Inverter P2)."""
from __future__ import annotations

import os

import streamlit as st

from house_config.battery_control import (
    BATTERY_CONTROL_VALUES,
    CONTROL_LABELS_DE,
    DEFAULT_BATTERY_CONTROL,
)
from house_config.entity_id_lock import (
    ID_PROVISIONAL_LABEL_KEY,
    is_id_locked,
)
from house_config.id_slug import slug_id
from house_config.inverter import (
    AC_GRID_TIED,
    AC_ISLAND,
    DEFAULT_AC_CONNECTION,
    DEFAULT_INVERTER_TYPE,
    INVERTER_TYPE_BATTERY,
    INVERTER_TYPE_HYBRID,
    INVERTER_TYPE_PV_STRING,
)
from house_config.label_uniqueness import allocate_unique_label
from runtime_store.persist_paths import resolve_config_json_path
from ui.auto_persist import auto_persist, payload_fingerprint
from ui.form_layout import labeled_number_input, labeled_selectbox, labeled_text_input
from ui.house_config_io import delete_inverter, list_inverters, upsert_inverter
from ui.label_select import (
    NEW_OPTION,
    align_label_select_session,
    label_select_choices,
    resolve_label_select,
)

_SESSION_SYNC_KEY = "planning_inv_sync_id"
_SESSION_FILE_STAMP_KEY = "planning_inv_file_stamp"
_SESSION_SELECT_PENDING_KEY = "planning_inv_select_pending"
_SESSION_SELECTED_ID_KEY = "planning_inv_selected_id"
_SESSION_SUPPRESS_AUTOPERSIST_KEY = "planning_inv_suppress_autopersist"
_SESSION_TEMPLATE_SOURCE_KEY = "planning_inv_template_source"
_SESSION_PROVISIONAL_LABEL_KEY = "planning_inv_provisional_label"

_TYPE_LABELS_DE = {
    INVERTER_TYPE_HYBRID: "Hybrid (PV + Batterie)",
    INVERTER_TYPE_PV_STRING: "PV-String (nur PV)",
    INVERTER_TYPE_BATTERY: "Batterie-WR (AC-gekoppelt)",
}
_AC_LABELS_DE = {
    AC_GRID_TIED: "Netzgekoppelt (Hausbus)",
    AC_ISLAND: "Insel (nur angeschlossene Lasten)",
}
_TYPE_VALUES = (
    INVERTER_TYPE_HYBRID,
    INVERTER_TYPE_PV_STRING,
    INVERTER_TYPE_BATTERY,
)
_AC_VALUES = (AC_GRID_TIED, AC_ISLAND)


def new_inverter_template(
    inverters: list[dict],
    *,
    source_id: str = "",
) -> dict:
    """Defaults for a new inverter — clone last selected, else empty hybrid."""
    by_id = {
        str(item.get("id", "")).strip(): item
        for item in inverters
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    source = by_id.get(str(source_id or "").strip())
    if source is None:
        return {
            "label": allocate_unique_label("Haupt-Wechselrichter", inverters),
            "type": DEFAULT_INVERTER_TYPE,
            "ac_connection": DEFAULT_AC_CONNECTION,
            "control": DEFAULT_BATTERY_CONTROL,
        }
    source_label = str(source.get("label") or source.get("id") or "Wechselrichter").strip()
    out = {
        "label": allocate_unique_label(f"{source_label} copy", inverters),
        "type": str(source.get("type") or DEFAULT_INVERTER_TYPE).strip().lower(),
        "ac_connection": str(
            source.get("ac_connection") or DEFAULT_AC_CONNECTION
        ).strip().lower(),
        "control": str(source.get("control") or DEFAULT_BATTERY_CONTROL).strip().lower(),
        "ehal_bindings": {},
    }
    for field in ("max_ac_power_kw", "max_pv_input_kw", "max_ac_charge_kw"):
        if field in source and source[field] not in (None, ""):
            out[field] = float(source[field])
    return out


def _scoped_key(session_scope: str, base: str) -> str:
    return f"{session_scope}__{base}"


def _inv_session_scope(selected_id: str, *, is_new: bool) -> str:
    return "__new__" if is_new else selected_id


def _config_file_stamp() -> str:
    path = resolve_config_json_path()
    try:
        return f"{os.path.abspath(path)}:{os.path.getmtime(path)}"
    except OSError:
        return os.path.abspath(path)


def _clear_scoped_widget_keys(session_scope: str) -> None:
    prefix = f"{session_scope}__"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            del st.session_state[key]


def _optional_kw(existing: dict, field: str) -> float | None:
    if field not in existing or existing[field] in (None, ""):
        return None
    return float(existing[field])


def _seed_inv_widget_state(session_scope: str, existing: dict) -> None:
    if existing:
        label = str(existing.get("label", "Haupt-Wechselrichter"))
        inv_type = str(existing.get("type") or DEFAULT_INVERTER_TYPE).strip().lower()
        ac = str(existing.get("ac_connection") or DEFAULT_AC_CONNECTION).strip().lower()
        control = str(existing.get("control") or DEFAULT_BATTERY_CONTROL).strip().lower()
        max_ac = _optional_kw(existing, "max_ac_power_kw")
        max_pv = _optional_kw(existing, "max_pv_input_kw")
        max_charge = _optional_kw(existing, "max_ac_charge_kw")
    else:
        label = allocate_unique_label("Haupt-Wechselrichter", list_inverters())
        inv_type = DEFAULT_INVERTER_TYPE
        ac = DEFAULT_AC_CONNECTION
        control = DEFAULT_BATTERY_CONTROL
        max_ac = None
        max_pv = None
        max_charge = None
    if inv_type not in _TYPE_VALUES:
        inv_type = DEFAULT_INVERTER_TYPE
    if ac not in _AC_VALUES:
        ac = DEFAULT_AC_CONNECTION
    if control not in BATTERY_CONTROL_VALUES:
        control = DEFAULT_BATTERY_CONTROL
    st.session_state[_scoped_key(session_scope, "planning_inv_label")] = label
    if session_scope == "__new__" or (existing and not is_id_locked(existing)):
        if existing:
            seed = str(existing.get(ID_PROVISIONAL_LABEL_KEY) or label).strip()
        else:
            seed = str(label).strip()
        st.session_state[_SESSION_PROVISIONAL_LABEL_KEY] = seed
    st.session_state[_scoped_key(session_scope, "planning_inv_type")] = _TYPE_LABELS_DE[
        inv_type
    ]
    st.session_state[_scoped_key(session_scope, "planning_inv_ac")] = _AC_LABELS_DE[ac]
    st.session_state[_scoped_key(session_scope, "planning_inv_control")] = (
        CONTROL_LABELS_DE[control]
    )
    st.session_state[_scoped_key(session_scope, "planning_inv_max_ac")] = (
        float(max_ac) if max_ac is not None else 0.0
    )
    st.session_state[_scoped_key(session_scope, "planning_inv_max_pv")] = (
        float(max_pv) if max_pv is not None else 0.0
    )
    st.session_state[_scoped_key(session_scope, "planning_inv_max_charge")] = (
        float(max_charge) if max_charge is not None else 0.0
    )


def _inv_widget_state_missing(session_scope: str) -> bool:
    return _scoped_key(session_scope, "planning_inv_label") not in st.session_state


def _sync_inv_session(session_scope: str, existing: dict, *, file_stamp: str) -> None:
    scope_changed = st.session_state.get(_SESSION_SYNC_KEY) != session_scope
    file_changed = st.session_state.get(_SESSION_FILE_STAMP_KEY) != file_stamp
    if scope_changed or file_changed or _inv_widget_state_missing(session_scope):
        _clear_scoped_widget_keys(session_scope)
        _seed_inv_widget_state(session_scope, existing)
        st.session_state[_SESSION_SYNC_KEY] = session_scope
        st.session_state[_SESSION_FILE_STAMP_KEY] = file_stamp


def _apply_pending_inv_select() -> None:
    pending = st.session_state.pop(_SESSION_SELECT_PENDING_KEY, None)
    if pending is not None:
        st.session_state["planning_inv_select"] = pending


def _inv_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in list_inverters()}


def _render_inv_select() -> dict:
    _apply_pending_inv_select()
    inv_map = _inv_by_id()
    inv_ids = sorted(inv_map.keys())
    options, id_by_display = label_select_choices(inv_map, inv_ids)
    align_label_select_session(
        select_key="planning_inv_select",
        selected_id_key=_SESSION_SELECTED_ID_KEY,
        entity_map=inv_map,
        entity_ids=inv_ids,
        id_by_display=id_by_display,
    )
    selected_display = labeled_selectbox(
        "Wechselrichter",
        options=options,
        key="planning_inv_select",
    )
    selected = resolve_label_select(selected_display, id_by_display)
    is_new = selected == NEW_OPTION
    if is_new:
        source_id = str(st.session_state.get(_SESSION_TEMPLATE_SOURCE_KEY) or "")
        existing = new_inverter_template(list_inverters(), source_id=source_id)
    else:
        sid = str(selected or "").strip()
        if sid and sid != NEW_OPTION:
            st.session_state[_SESSION_TEMPLATE_SOURCE_KEY] = sid
            st.session_state[_SESSION_SELECTED_ID_KEY] = sid
        existing = inv_map.get(selected, {})
    session_scope = _inv_session_scope(selected, is_new=is_new)
    _sync_inv_session(session_scope, existing, file_stamp=_config_file_stamp())
    return {
        "inv_ids": inv_ids,
        "is_new": is_new,
        "existing": existing,
        "session_scope": session_scope,
    }


def _optional_positive_from_widget(value: float) -> float | None:
    if value is None or float(value) <= 0.0:
        return None
    return float(value)


def _render_inv_fields(session_scope: str, *, existing: dict) -> dict:
    label = labeled_text_input(
        "Bezeichnung",
        key=_scoped_key(session_scope, "planning_inv_label"),
    )
    type_label = labeled_selectbox(
        "Typ",
        options=[_TYPE_LABELS_DE[v] for v in _TYPE_VALUES],
        key=_scoped_key(session_scope, "planning_inv_type"),
        help="hybrid = PV+Batterie DC; pv_string = nur PV; battery = AC-gekoppelte Batterie.",
    )
    label_to_type = {v: k for k, v in _TYPE_LABELS_DE.items()}
    inv_type = label_to_type.get(str(type_label), DEFAULT_INVERTER_TYPE)
    ac_label = labeled_selectbox(
        "AC-Anschluss",
        options=[_AC_LABELS_DE[v] for v in _AC_VALUES],
        key=_scoped_key(session_scope, "planning_inv_ac"),
        help="netzgekoppelt = Hausbus; Insel = nur angeschlossene Lasten "
        "(ersetzt früheres batteries[].kind=isolated).",
    )
    label_to_ac = {v: k for k, v in _AC_LABELS_DE.items()}
    ac = label_to_ac.get(str(ac_label), DEFAULT_AC_CONNECTION)
    control_labels = [CONTROL_LABELS_DE[v] for v in sorted(BATTERY_CONTROL_VALUES)]
    control_label = labeled_selectbox(
        "Steuerbarkeit",
        options=control_labels,
        key=_scoped_key(session_scope, "planning_inv_control"),
    )
    label_to_control = {v: k for k, v in CONTROL_LABELS_DE.items()}
    control = label_to_control.get(str(control_label), DEFAULT_BATTERY_CONTROL)
    max_ac = labeled_number_input(
        "Max. AC-Leistung (kW, 0 = kein Cap)",
        min_value=0.0,
        step=0.1,
        key=_scoped_key(session_scope, "planning_inv_max_ac"),
    )
    max_pv = labeled_number_input(
        "Max. PV-Eingang (kW, 0 = kein Cap)",
        min_value=0.0,
        step=0.1,
        key=_scoped_key(session_scope, "planning_inv_max_pv"),
    )
    max_charge = labeled_number_input(
        "Max. AC-Laden aus Netz (kW, 0 = kein Cap)",
        min_value=0.0,
        step=0.1,
        key=_scoped_key(session_scope, "planning_inv_max_charge"),
    )
    owned_by = str(existing.get("owned_by") or "").strip()
    if owned_by:
        st.caption(
            f"Integrierter Wechselrichter der Batterie `{owned_by}` "
            "(Lifecycle mit der Batterie)."
        )
    return {
        "label": label,
        "type": inv_type,
        "ac_connection": ac,
        "control": control,
        "max_ac_power_kw": _optional_positive_from_widget(max_ac),
        "max_pv_input_kw": _optional_positive_from_widget(max_pv),
        "max_ac_charge_kw": _optional_positive_from_widget(max_charge),
        "owned_by": owned_by,
        "ehal_bindings": dict(existing.get("ehal_bindings") or {}),
    }


def _inv_save_payload(fields: dict) -> dict:
    payload = {
        "label": fields["label"],
        "type": fields["type"],
        "ac_connection": fields["ac_connection"],
        "control": fields["control"],
        "ehal_bindings": dict(fields.get("ehal_bindings") or {}),
    }
    for field in ("max_ac_power_kw", "max_pv_input_kw", "max_ac_charge_kw"):
        if fields.get(field) is not None:
            payload[field] = fields[field]
    owned = str(fields.get("owned_by") or "").strip()
    if owned:
        payload["owned_by"] = owned
    provisional = str(
        fields.get(ID_PROVISIONAL_LABEL_KEY)
        or st.session_state.get(_SESSION_PROVISIONAL_LABEL_KEY)
        or ""
    ).strip()
    if provisional:
        payload[ID_PROVISIONAL_LABEL_KEY] = provisional
    return payload


def _save_inv(
    fields: dict,
    *,
    stable_id: str,
    is_new: bool,
    force_id_from_label: bool = False,
) -> str | None:
    try:
        persisted_id = upsert_inverter(
            _inv_save_payload(fields),
            stable_id=stable_id,
            force_id_from_label=force_id_from_label,
        )
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
    if is_new or (stable_id and persisted_id != stable_id):
        st.session_state[_SESSION_SELECT_PENDING_KEY] = persisted_id
        st.session_state[_SESSION_SYNC_KEY] = None
        st.session_state.pop(_SESSION_PROVISIONAL_LABEL_KEY, None)
    return persisted_id


def _persist_inv_form(
    fields: dict,
    *,
    stable_id: str,
    entity_id: str,
    is_new: bool,
    ready: bool,
) -> None:
    payload = {"id": entity_id, **_inv_save_payload(fields)}
    persist_key = f"planning_inv::{stable_id or entity_id}"
    suppress = bool(st.session_state.pop(_SESSION_SUPPRESS_AUTOPERSIST_KEY, False))
    if suppress and ready:
        st.session_state[f"_auto_persist_fp::{persist_key}"] = payload_fingerprint(
            payload
        )
        wrote = False
    else:
        wrote = auto_persist(
            state_key=persist_key,
            payload=payload,
            save=lambda: _save_inv(
                fields,
                stable_id=stable_id,
                is_new=is_new,
            ),
            ready=ready,
        )
    if wrote:
        st.rerun()


def _render_inv_id_from_label(stable_id: str, fields: dict) -> None:
    label = str(fields.get("label") or "").strip()
    if not label or not stable_id:
        return
    desired = slug_id(label)
    if desired == stable_id:
        return
    if st.button(
        "ID aus Bezeichnung übernehmen",
        key="planning_inv_id_from_label",
        help=f"Aktuelle ID `{stable_id}` → aus Bezeichnung `{desired}` (danach fest).",
    ):
        persisted = _save_inv(
            fields,
            stable_id=stable_id,
            is_new=False,
            force_id_from_label=True,
        )
        if persisted:
            st.success(f"ID gesetzt: `{persisted}`")
            st.rerun()


def _render_inv_delete(stable_id: str) -> None:
    if not st.button("Wechselrichter entfernen", key="planning_inv_delete"):
        return
    try:
        delete_inverter(stable_id)
    except ValueError as exc:
        st.error(str(exc))
        return
    remaining_ids = sorted(_inv_by_id().keys())
    fallback = remaining_ids[0] if remaining_ids else NEW_OPTION
    _clear_scoped_widget_keys(stable_id)
    _clear_scoped_widget_keys("__new__")
    st.session_state.pop(_SESSION_SELECTED_ID_KEY, None)
    st.session_state.pop(f"_auto_persist_fp::planning_inv::{stable_id}", None)
    st.session_state[_SESSION_SELECT_PENDING_KEY] = fallback
    st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
    st.session_state[_SESSION_SYNC_KEY] = None
    if fallback == NEW_OPTION:
        st.session_state[_SESSION_SUPPRESS_AUTOPERSIST_KEY] = True
    st.success("Wechselrichter entfernt.")
    st.rerun()


def render_inverter_planning_tab() -> None:
    st.caption(
        "Wechselrichter verknüpfen PV-Anlagen und Batterien (`inverter_id`). "
        "Insel-WR mit `owned_by` entstehen mit physischen Powerstations; "
        "EHAL-Namespace später `inv.<Kennung>.*`."
    )
    ctx = _render_inv_select()
    is_new = ctx["is_new"]
    fields = _render_inv_fields(ctx["session_scope"], existing=ctx["existing"])
    stable_id = "" if is_new else str(ctx["existing"].get("id", ""))
    label = fields["label"]
    ready = bool(str(label or "").strip())
    taken = {iid for iid in ctx["inv_ids"] if iid != stable_id}
    entity_id = stable_id.strip() or slug_id(label or "wechselrichter", existing=taken)
    _persist_inv_form(
        fields,
        stable_id=stable_id,
        entity_id=entity_id,
        is_new=is_new,
        ready=ready,
    )
    if not is_new and stable_id:
        _render_inv_id_from_label(stable_id, fields)
        _render_inv_delete(stable_id)
