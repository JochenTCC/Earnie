"""PV-Tab im Hauskonfigurator."""
from __future__ import annotations

import os

import streamlit as st

from house_config.id_slug import slug_id
from runtime_store.persist_paths import resolve_config_json_path
from ui.house_config_io import (
    delete_pv_system,
    get_runtime_scenario_refs,
    list_pv_systems,
    load_house_profiles,
    upsert_pv_system,
)
from ui.auto_persist import auto_persist
from ui.form_layout import labeled_number_input, labeled_selectbox, labeled_text_input
from ui.label_select import (
    NEW_OPTION,
    align_label_select_session,
    label_select_choices,
    resolve_label_select,
)

_SESSION_SYNC_KEY = "planning_pv_sync_id"
_SESSION_FILE_STAMP_KEY = "planning_pv_file_stamp"
_SESSION_SELECT_PENDING_KEY = "planning_pv_select_pending"
_SESSION_SELECTED_ID_KEY = "planning_pv_selected_id"


def _scoped_key(session_scope: str, base: str) -> str:
    return f"{session_scope}__{base}"


def _pv_session_scope(selected_id: str, *, is_new: bool) -> str:
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


def _profile_pv_defaults(profile: dict) -> tuple[float, float]:
    return (
        float(profile.get("default_pv_tilt", 18.0)),
        float(profile.get("default_pv_azimuth", 0.0)),
    )


def _apply_profile_pv_defaults(session_scope: str, profiles: dict[str, dict]) -> None:
    raw = st.session_state.get(_scoped_key(session_scope, "planning_pv_defaults_profile"))
    profile_id = str(raw or "").strip()
    if profile_id not in profiles:
        # Bezeichnung option → id
        for pid, profile in profiles.items():
            if str(profile.get("label") or pid) == profile_id:
                profile_id = pid
                break
    if profile_id not in profiles:
        return
    tilt, azimuth = _profile_pv_defaults(profiles[profile_id])
    st.session_state[_scoped_key(session_scope, "planning_pv_tilt")] = int(tilt)
    st.session_state[_scoped_key(session_scope, "planning_pv_azimuth")] = int(azimuth)


def _default_profile_for_pv(profiles: dict[str, dict]) -> dict:
    refs = get_runtime_scenario_refs()
    profile_id = str(refs.get("house_profile_id", "") or "").strip()
    if profile_id and profile_id in profiles:
        return profiles[profile_id]
    if profiles:
        return next(iter(profiles.values()))
    return {}


def _seed_pv_widget_state(
    session_scope: str,
    existing: dict,
    *,
    profiles: dict[str, dict],
    default_profile: dict,
) -> None:
    from house_config.label_uniqueness import allocate_unique_label

    default_tilt, default_azimuth = _profile_pv_defaults(default_profile)
    if existing:
        label = str(existing.get("label", "Dach Süd"))
        kwp = float(existing.get("pv_kwp", existing.get("kwp", 10.0)))
        tilt = int(existing.get("pv_tilt", existing.get("tilt", default_tilt)))
        azimuth = int(existing.get("pv_azimuth", existing.get("azimuth", default_azimuth)))
    else:
        label = allocate_unique_label("Dach Süd", list_pv_systems())
        kwp = 10.0
        tilt = int(default_tilt)
        azimuth = int(default_azimuth)
        if profiles:
            profile_ids = sorted(profiles.keys())
            default_profile_id = str(default_profile.get("id", profile_ids[0]))
            st.session_state[_scoped_key(session_scope, "planning_pv_defaults_profile")] = (
                default_profile_id if default_profile_id in profile_ids else profile_ids[0]
            )

    st.session_state[_scoped_key(session_scope, "planning_pv_label")] = label
    st.session_state[_scoped_key(session_scope, "planning_pv_kwp")] = kwp
    st.session_state[_scoped_key(session_scope, "planning_pv_tilt")] = tilt
    st.session_state[_scoped_key(session_scope, "planning_pv_azimuth")] = azimuth


def _pv_widget_state_missing(session_scope: str) -> bool:
    """True when sync metadata exists but scoped widget keys were dropped (e.g. page navigation)."""
    return _scoped_key(session_scope, "planning_pv_label") not in st.session_state


def _sync_pv_session(
    session_scope: str,
    existing: dict,
    *,
    file_stamp: str,
    profiles: dict[str, dict],
    default_profile: dict,
) -> None:
    scope_changed = st.session_state.get(_SESSION_SYNC_KEY) != session_scope
    file_changed = st.session_state.get(_SESSION_FILE_STAMP_KEY) != file_stamp
    widget_state_missing = _pv_widget_state_missing(session_scope)
    if scope_changed or file_changed or widget_state_missing:
        _clear_scoped_widget_keys(session_scope)
        _seed_pv_widget_state(
            session_scope,
            existing,
            profiles=profiles,
            default_profile=default_profile,
        )
        st.session_state[_SESSION_SYNC_KEY] = session_scope
        st.session_state[_SESSION_FILE_STAMP_KEY] = file_stamp


def _apply_pending_pv_select() -> None:
    pending = st.session_state.pop(_SESSION_SELECT_PENDING_KEY, None)
    if pending is not None:
        st.session_state["planning_pv_select"] = pending


def _initial_pv_index(system_ids: list[str]) -> int | None:
    if "planning_pv_select" in st.session_state:
        return None
    refs = get_runtime_scenario_refs().get("pv_system_ids") or []
    for pv_id in refs:
        if pv_id in system_ids:
            return system_ids.index(pv_id) + 1
    return None


def _pv_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in list_pv_systems()}


def render_pv_planning_tab() -> None:
    st.caption(
        "Optional — ohne PV-Anlage bleibt die Prognose bei 0 kW (z. B. reine Batterie-Arbitrage)."
    )
    _apply_pending_pv_select()
    system_map = _pv_by_id()
    system_ids = sorted(system_map.keys())
    options, id_by_display = label_select_choices(system_map, system_ids)
    align_label_select_session(
        select_key="planning_pv_select",
        selected_id_key=_SESSION_SELECTED_ID_KEY,
        entity_map=system_map,
        entity_ids=system_ids,
        id_by_display=id_by_display,
    )
    initial_index = _initial_pv_index(system_ids)

    if initial_index is not None:
        selected_display = labeled_selectbox(
            "PV-Anlage",
            options=options,
            index=initial_index,
            key="planning_pv_select",
        )
    else:
        selected_display = labeled_selectbox(
            "PV-Anlage",
            options=options,
            key="planning_pv_select",
        )
    selected = resolve_label_select(selected_display, id_by_display)
    is_new = selected == NEW_OPTION
    existing = system_map.get(selected, {}) if not is_new else {}
    if not is_new:
        st.session_state[_SESSION_SELECTED_ID_KEY] = selected

    profiles = load_house_profiles().get("profiles", {})
    default_profile = _default_profile_for_pv(profiles)
    session_scope = _pv_session_scope(selected, is_new=is_new)
    file_stamp = _config_file_stamp()
    _sync_pv_session(
        session_scope,
        existing,
        file_stamp=file_stamp,
        profiles=profiles,
        default_profile=default_profile,
    )

    label = labeled_text_input(
        "Bezeichnung",
        key=_scoped_key(session_scope, "planning_pv_label"),
    )
    stable_id = "" if is_new else str(existing.get("id", ""))

    if is_new and profiles:
        profile_ids = sorted(profiles.keys())
        profile_options, profile_id_by_display = label_select_choices(
            profiles, profile_ids, new_option=None
        )
        profile_key = _scoped_key(session_scope, "planning_pv_defaults_profile")
        # Legacy session may hold a profile id — map to Bezeichnung option.
        raw_profile = st.session_state.get(profile_key)
        if raw_profile in profiles and raw_profile not in profile_id_by_display:
            st.session_state[profile_key] = str(
                profiles[raw_profile].get("label") or raw_profile
            )
        profile_pick_display = labeled_selectbox(
            "Defaults aus Hausprofil",
            options=profile_options,
            key=profile_key,
            on_change=_apply_profile_pv_defaults,
            args=(session_scope, profiles),
        )
        profile_pick = resolve_label_select(profile_pick_display, profile_id_by_display)
        picked = profiles[profile_pick]
        st.caption(
            f"Vorschlag Neigung/Azimut aus Profil "
            f"({_profile_pv_defaults(picked)[0]:.0f}° / {_profile_pv_defaults(picked)[1]:.0f}°) "
            f"— im Formular überschreibbar."
        )

    kwp = labeled_number_input(
        "Leistung (kWp)",
        min_value=0.1,
        step=0.1,
        key=_scoped_key(session_scope, "planning_pv_kwp"),
    )
    tilt = labeled_number_input(
        "Dachneigung (°)",
        min_value=0,
        max_value=90,
        key=_scoped_key(session_scope, "planning_pv_tilt"),
    )
    azimuth = labeled_number_input(
        "Ausrichtung Azimut (°)",
        min_value=-180,
        max_value=180,
        help="0 = Süd, -90 = Ost, 90 = West",
        key=_scoped_key(session_scope, "planning_pv_azimuth"),
    )

    ready = bool(str(label or "").strip()) and float(kwp or 0) > 0
    taken = {sid for sid in system_ids if sid != stable_id}
    entity_id = stable_id.strip() or slug_id(label or "pv_anlage", existing=taken)
    payload = {
        "id": entity_id,
        "label": label,
        "kwp": kwp,
        "pv_tilt": float(tilt),
        "pv_azimuth": float(azimuth),
    }

    def _save_pv() -> None:
        try:
            upsert_pv_system(
                {
                    "label": label,
                    "kwp": kwp,
                    "pv_tilt": float(tilt),
                    "pv_azimuth": float(azimuth),
                },
                stable_id=stable_id,
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
        if is_new:
            st.session_state[_SESSION_SELECT_PENDING_KEY] = entity_id
            st.session_state[_SESSION_SYNC_KEY] = None
            st.rerun()

    wrote = auto_persist(
        state_key=f"planning_pv::{entity_id}",
        payload=payload,
        save=_save_pv,
        ready=ready,
    )
    if wrote:
        st.rerun()

    if not is_new and stable_id:
        if st.button("PV-Anlage entfernen", key="planning_pv_delete"):
            try:
                delete_pv_system(stable_id)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state[_SESSION_SELECT_PENDING_KEY] = NEW_OPTION
                st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
                st.session_state[_SESSION_SYNC_KEY] = None
                st.success("PV-Anlage entfernt.")
                st.rerun()
