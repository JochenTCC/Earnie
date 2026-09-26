"""Plant-level Hauskonfigurator fields (house-wide, not per profile)."""
from __future__ import annotations

import streamlit as st

from ui.auto_persist import auto_persist
from ui.form_layout import labeled_number_input
from ui.house_config_io import load_house_profiles, save_house_profiles

_PLANT_EXPORT_KEY = "house_config_plant_max_export_kw"
_PLANT_EXPORT_ENABLED_KEY = "house_config_plant_max_export_enabled"


def _seed_plant_export_widgets(plant: dict) -> None:
    raw = plant.get("max_export_power_kw")
    has_cap = raw is not None and raw != ""
    if _PLANT_EXPORT_ENABLED_KEY not in st.session_state:
        st.session_state[_PLANT_EXPORT_ENABLED_KEY] = bool(has_cap)
    if _PLANT_EXPORT_KEY not in st.session_state:
        try:
            st.session_state[_PLANT_EXPORT_KEY] = float(raw) if has_cap else 5.0
        except (TypeError, ValueError):
            st.session_state[_PLANT_EXPORT_KEY] = 5.0


def render_plant_export_limit() -> None:
    """Optional static max grid export (kW) on ``plant.max_export_power_kw``."""
    house = load_house_profiles()
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    _seed_plant_export_widgets(plant if isinstance(plant, dict) else {})

    st.markdown("##### Einspeisebegrenzung (Anlage)")
    st.caption(
        "Statische Obergrenze für Netz-Einspeisung (kW). "
        "Leer/aus = keine HK-Grenze; externe Grenzen und "
        "zahlende Einspeisetarife können zusätzlich greifen."
    )
    enabled = st.checkbox(
        "Max. Einspeiseleistung begrenzen",
        key=_PLANT_EXPORT_ENABLED_KEY,
    )
    max_kw: float | None = None
    if enabled:
        max_kw = float(
            labeled_number_input(
                "Max. Einspeiseleistung (kW)",
                min_value=0.01,
                format="%.2f",
                key=_PLANT_EXPORT_KEY,
                help="plant.max_export_power_kw — harte Decke für MILP und Live.",
            )
        )

    def _persist() -> None:
        doc = load_house_profiles()
        plant_out = (
            dict(doc.get("plant") or {})
            if isinstance(doc.get("plant"), dict)
            else {}
        )
        if max_kw is not None and max_kw > 0.0:
            plant_out["max_export_power_kw"] = round(float(max_kw), 3)
        else:
            plant_out.pop("max_export_power_kw", None)
        if plant_out:
            doc["plant"] = plant_out
        else:
            doc.pop("plant", None)
        save_house_profiles(doc)

    auto_persist(
        state_key="house_config_plant_export",
        payload={"enabled": enabled, "max_kw": max_kw},
        save=_persist,
    )
