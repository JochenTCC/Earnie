"""PV-Tab im Hauskonfigurator."""
from __future__ import annotations

import streamlit as st

from ui.house_config_io import (
    get_runtime_scenario_refs,
    list_pv_systems,
    load_house_profiles,
    upsert_pv_system,
)


def _pv_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in list_pv_systems()}


def _profile_pv_defaults(profile: dict) -> tuple[float, float]:
    return (
        float(profile.get("default_pv_tilt", 25.0)),
        float(profile.get("default_pv_azimuth", 0.0)),
    )


def _default_profile_for_pv(profiles: dict[str, dict]) -> dict:
    refs = get_runtime_scenario_refs()
    profile_id = str(refs.get("house_profile_id", "") or "").strip()
    if profile_id and profile_id in profiles:
        return profiles[profile_id]
    if profiles:
        return next(iter(profiles.values()))
    return {}


def render_pv_planning_tab() -> None:
    systems = list_pv_systems()
    system_map = _pv_by_id()
    options = ["— neu —", *sorted(system_map.keys())]
    selected = st.selectbox("PV-Anlage", options=options, key="planning_pv_select")
    is_new = selected == "— neu —"
    existing = system_map.get(selected, {}) if not is_new else {}

    profiles = load_house_profiles().get("profiles", {})
    default_profile = _default_profile_for_pv(profiles)
    default_tilt, default_azimuth = _profile_pv_defaults(default_profile)

    label = st.text_input(
        "Bezeichnung",
        value=existing.get("label", "Dach Süd"),
        key="planning_pv_label",
    )
    stable_id = "" if is_new else str(existing.get("id", ""))
    if stable_id:
        st.caption(f"Anlagen-ID: `{stable_id}`")

    if is_new and profiles:
        profile_ids = sorted(profiles.keys())
        profile_labels = {
            pid: f"{profiles[pid].get('label', pid)} ({pid})" for pid in profile_ids
        }
        default_profile_id = str(default_profile.get("id", profile_ids[0]))
        profile_pick = st.selectbox(
            "Defaults aus Hausprofil",
            options=profile_ids,
            index=profile_ids.index(default_profile_id)
            if default_profile_id in profile_ids
            else 0,
            format_func=lambda pid: profile_labels[pid],
            key="planning_pv_defaults_profile",
        )
        picked = profiles[profile_pick]
        default_tilt, default_azimuth = _profile_pv_defaults(picked)
        st.caption(
            f"Vorschlag Neigung/Azimut aus Profil — im Formular überschreibbar."
        )

    kwp = st.number_input(
        "Leistung (kWp)",
        min_value=0.1,
        value=float(existing.get("pv_kwp", existing.get("kwp", 10.0))),
        step=0.1,
        key="planning_pv_kwp",
    )
    tilt = st.number_input(
        "Dachneigung (°)",
        min_value=0,
        max_value=90,
        value=int(existing.get("pv_tilt", existing.get("tilt", default_tilt))),
        key="planning_pv_tilt",
    )
    azimuth = st.number_input(
        "Ausrichtung Azimut (°)",
        min_value=-180,
        max_value=180,
        value=int(existing.get("pv_azimuth", existing.get("azimuth", default_azimuth))),
        help="0 = Süd, -90 = Ost, 90 = West",
        key="planning_pv_azimuth",
    )

    if st.button("PV-Anlage speichern", type="primary", key="planning_pv_save"):
        upsert_pv_system(
            {
                "label": label,
                "kwp": kwp,
                "pv_tilt": float(tilt),
                "pv_azimuth": float(azimuth),
            },
            stable_id=stable_id,
        )
        st.success("PV-Anlage gespeichert.")
        st.rerun()
