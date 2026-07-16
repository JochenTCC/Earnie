"""PV-Tab im Hauskonfigurator."""
from __future__ import annotations

import os

import streamlit as st

from house_config.id_slug import slug_id
from runtime_store.persist_paths import resolve_config_json_path
from ui.house_config_io import (
    get_runtime_scenario_refs,
    list_pv_systems,
    load_house_profiles,
    upsert_pv_system,
)
from ui.house_config_sticky_save import sticky_save_bar

_SESSION_SYNC_KEY = "planning_pv_sync_id"
_SESSION_FILE_STAMP_KEY = "planning_pv_file_stamp"
_SESSION_SELECT_PENDING_KEY = "planning_pv_select_pending"


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
    profile_id = st.session_state.get(_scoped_key(session_scope, "planning_pv_defaults_profile"))
    if not profile_id or profile_id not in profiles:
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
    default_tilt, default_azimuth = _profile_pv_defaults(default_profile)
    if existing:
        label = str(existing.get("label", "Dach Süd"))
        kwp = float(existing.get("pv_kwp", existing.get("kwp", 10.0)))
        tilt = int(existing.get("pv_tilt", existing.get("tilt", default_tilt)))
        azimuth = int(existing.get("pv_azimuth", existing.get("azimuth", default_azimuth)))
    else:
        label = "Dach Süd"
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
    pv_id = str(get_runtime_scenario_refs().get("pv_system_id", "") or "").strip()
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
    options = ["— neu —", *system_ids]
    initial_index = _initial_pv_index(system_ids)
    if initial_index is not None:
        selected = st.selectbox(
            "PV-Anlage",
            options=options,
            index=initial_index,
            key="planning_pv_select",
        )
    else:
        selected = st.selectbox("PV-Anlage", options=options, key="planning_pv_select")
    is_new = selected == "— neu —"
    existing = system_map.get(selected, {}) if not is_new else {}

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

    label = st.text_input(
        "Bezeichnung",
        key=_scoped_key(session_scope, "planning_pv_label"),
    )
    stable_id = "" if is_new else str(existing.get("id", ""))
    if stable_id:
        st.caption(f"Anlagen-ID: `{stable_id}`")

    if is_new and profiles:
        profile_ids = sorted(profiles.keys())
        profile_labels = {
            pid: f"{profiles[pid].get('label', pid)} ({pid})" for pid in profile_ids
        }
        profile_pick = st.selectbox(
            "Defaults aus Hausprofil",
            options=profile_ids,
            format_func=lambda pid: profile_labels[pid],
            key=_scoped_key(session_scope, "planning_pv_defaults_profile"),
            on_change=_apply_profile_pv_defaults,
            args=(session_scope, profiles),
        )
        picked = profiles[profile_pick]
        st.caption(
            f"Vorschlag Neigung/Azimut aus Profil "
            f"({_profile_pv_defaults(picked)[0]:.0f}° / {_profile_pv_defaults(picked)[1]:.0f}°) "
            f"— im Formular überschreibbar."
        )

    kwp = st.number_input(
        "Leistung (kWp)",
        min_value=0.1,
        step=0.1,
        key=_scoped_key(session_scope, "planning_pv_kwp"),
    )
    tilt = st.number_input(
        "Dachneigung (°)",
        min_value=0,
        max_value=90,
        key=_scoped_key(session_scope, "planning_pv_tilt"),
    )
    azimuth = st.number_input(
        "Ausrichtung Azimut (°)",
        min_value=-180,
        max_value=180,
        help="0 = Süd, -90 = Ost, 90 = West",
        key=_scoped_key(session_scope, "planning_pv_azimuth"),
    )

    sticky_save_bar()
    if st.button("PV-Anlage speichern", type="primary", key="planning_pv_save"):
        taken = {sid for sid in system_ids if sid != stable_id}
        entity_id = stable_id.strip() or slug_id(label or "pv_anlage", existing=taken)
        upsert_pv_system(
            {
                "label": label,
                "kwp": kwp,
                "pv_tilt": float(tilt),
                "pv_azimuth": float(azimuth),
            },
            stable_id=stable_id,
        )
        st.session_state[_SESSION_SELECT_PENDING_KEY] = entity_id
        st.session_state[_SESSION_FILE_STAMP_KEY] = _config_file_stamp()
        st.session_state[_SESSION_SYNC_KEY] = None
        st.success("PV-Anlage gespeichert.")
        st.rerun()
