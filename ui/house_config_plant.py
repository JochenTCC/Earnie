"""Plant-level Hauskonfigurator fields (house-wide, not per profile)."""
from __future__ import annotations

import streamlit as st

from ui.auto_persist import auto_persist
from ui.form_layout import labeled_checkbox, labeled_number_input
from ui.house_config_io import load_house_profiles, save_house_profiles

_PLANT_EXPORT_KEY = "house_config_plant_max_export_kw"
_PLANT_EXPORT_ENABLED_KEY = "house_config_plant_max_export_enabled"
_PLANT_GM_AT_HOUSE_KEY = "house_config_plant_grid_meter_at_house"
_PLANT_GM_SINGLE_TARIFF_KEY = "house_config_plant_grid_meter_single_tariff"


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
        from house_config.required_signal_activation import activate_plant_required

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
            doc["plant"] = activate_plant_required(plant_out)
        else:
            doc.pop("plant", None)
        save_house_profiles(doc)

    auto_persist(
        state_key="house_config_plant_export",
        payload={"enabled": enabled, "max_kw": max_kw},
        save=_persist,
    )


def _seed_plant_grid_meter_widgets(plant: dict) -> None:
    raw = plant.get("grid_meter") if isinstance(plant.get("grid_meter"), dict) else {}
    if _PLANT_GM_AT_HOUSE_KEY not in st.session_state:
        st.session_state[_PLANT_GM_AT_HOUSE_KEY] = bool(
            raw.get("at_house_connection", False)
        )
    if _PLANT_GM_SINGLE_TARIFF_KEY not in st.session_state:
        st.session_state[_PLANT_GM_SINGLE_TARIFF_KEY] = bool(
            raw.get("single_tariff", False)
        )


def render_plant_grid_meter_assertions() -> None:
    """Topology P1: root meter assertions for the live path."""
    house = load_house_profiles()
    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    plant_map = plant if isinstance(plant, dict) else {}
    _seed_plant_grid_meter_widgets(plant_map)

    st.markdown("##### Netz-Zähler (Anlage / Live)")
    st.caption(
        "Live-Pfad: beide Aussagen müssen zutreffen. "
        "Sitzt der Zähler direkt am Hausanschluss? "
        "Gibt es nur einen Tarif? "
        "Regelt ein anderes Gerät selbst auf diesen Zähler? "
        "(Fremdregler → Hausbatterie `regulates_on`.)"
    )
    at_house = labeled_checkbox(
        "Zähler sitzt direkt am Hausanschluss",
        key=_PLANT_GM_AT_HOUSE_KEY,
        help="plant.grid_meter.at_house_connection",
    )
    single = labeled_checkbox(
        "Nur ein Import- und ein Exporttarif hinter diesem Zähler",
        key=_PLANT_GM_SINGLE_TARIFF_KEY,
        help="plant.grid_meter.single_tariff",
    )

    def _persist() -> None:
        from house_config.required_signal_activation import activate_plant_required

        doc = load_house_profiles()
        plant_out = (
            dict(doc.get("plant") or {})
            if isinstance(doc.get("plant"), dict)
            else {}
        )
        plant_out["grid_meter"] = {
            "at_house_connection": bool(at_house),
            "single_tariff": bool(single),
        }
        plant_out.pop("pv_covers_all_inverters", None)
        doc["plant"] = activate_plant_required(plant_out)
        save_house_profiles(doc)

    auto_persist(
        state_key="house_config_plant_grid_meter",
        payload={
            "at_house": bool(at_house),
            "single": bool(single),
        },
        save=_persist,
    )
