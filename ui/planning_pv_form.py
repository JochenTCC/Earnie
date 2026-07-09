"""PV-Tab im Hauskonfigurator."""
from __future__ import annotations

import streamlit as st

from ui.house_config_io import list_pv_systems, upsert_pv_system


def _pv_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in list_pv_systems()}


def render_pv_planning_tab() -> None:
    systems = list_pv_systems()
    system_map = _pv_by_id()
    options = ["— neu —", *sorted(system_map.keys())]
    selected = st.selectbox("PV-Anlage", options=options, key="planning_pv_select")
    is_new = selected == "— neu —"
    existing = system_map.get(selected, {}) if not is_new else {}

    label = st.text_input(
        "Bezeichnung",
        value=existing.get("label", "Dach Süd"),
        key="planning_pv_label",
    )
    stable_id = "" if is_new else str(existing.get("id", ""))
    if stable_id:
        st.caption(f"Anlagen-ID: `{stable_id}`")

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
        value=int(existing.get("pv_tilt", existing.get("tilt", 25))),
        key="planning_pv_tilt",
    )
    azimuth = st.number_input(
        "Ausrichtung Azimut (°)",
        min_value=-180,
        max_value=180,
        value=int(existing.get("pv_azimuth", existing.get("azimuth", 0))),
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
