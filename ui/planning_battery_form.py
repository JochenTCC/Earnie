"""Batterie-Tab im Hauskonfigurator."""
from __future__ import annotations

import streamlit as st

from ui.house_config_io import list_batteries, upsert_battery


def _battery_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in list_batteries()}


def render_battery_planning_tab() -> None:
    batteries = list_batteries()
    battery_map = _battery_by_id()
    options = ["— neu —", *sorted(battery_map.keys())]
    selected = st.selectbox("Batterie", options=options, key="planning_battery_select")
    is_new = selected == "— neu —"
    existing = battery_map.get(selected, {}) if not is_new else {}

    label = st.text_input(
        "Bezeichnung",
        value=existing.get("label", "5 kWh Speicher"),
        key="planning_battery_label",
    )
    stable_id = "" if is_new else str(existing.get("id", ""))
    if stable_id:
        st.caption(f"Batterie-ID: `{stable_id}`")

    capacity = st.number_input(
        "Kapazität (kWh)",
        min_value=0.1,
        value=float(existing.get("battery_capacity_kwh", 5.0)),
        step=0.5,
        key="planning_battery_capacity",
    )
    max_power = st.number_input(
        "Max. Lade-/Entladeleistung (kW)",
        min_value=0.1,
        value=float(existing.get("battery_max_power_kw", 2.5)),
        step=0.1,
        key="planning_battery_power",
    )
    efficiency = st.number_input(
        "Wirkungsgrad",
        min_value=0.5,
        max_value=1.0,
        value=float(existing.get("battery_efficiency", 0.97)),
        step=0.01,
        key="planning_battery_efficiency",
    )
    min_soc = st.number_input(
        "Minimaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        value=float(existing.get("battery_min_soc", 10.0)),
        key="planning_battery_min_soc",
    )
    max_soc = st.number_input(
        "Maximaler SoC (%)",
        min_value=0.0,
        max_value=100.0,
        value=float(existing.get("battery_max_soc", 100.0)),
        key="planning_battery_max_soc",
    )
    threshold_percent = st.number_input(
        "Leistungs-Schwelle (%)",
        min_value=1.0,
        max_value=100.0,
        value=float(existing.get("threshold_power", 0.05)) * 100.0,
        help="Anteil der max. Lade-/Entladeleistung.",
        key="planning_battery_threshold",
    )

    if st.button("Batterie speichern", type="primary", key="planning_battery_save"):
        upsert_battery(
            {
                "label": label,
                "battery_capacity_kwh": capacity,
                "battery_max_power_kw": max_power,
                "battery_efficiency": efficiency,
                "battery_min_soc": min_soc,
                "battery_max_soc": max_soc,
                "threshold_power": threshold_percent / 100.0,
            },
            stable_id=stable_id,
        )
        st.success("Batterie gespeichert.")
        st.rerun()
