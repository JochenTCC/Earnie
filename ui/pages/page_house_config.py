"""Hauskonfigurator: Verbraucher, Jahresverbrauch und Grundlast-Vorschau."""
from __future__ import annotations

import streamlit as st

from ui.help_hint import render_page_title_with_help
from ui.house_config_io import load_house_profiles, preview_baseload, upsert_house_profile

_HELP = (
    "Backtesting-Planung: Jahresverbrauch und Verbraucher erfassen. "
    "Grundlast = max(5 % Jahresverbrauch, Jahresverbrauch − Summe Verbraucher). "
    "Speichert nach `config/house_profiles.json`."
)


def render() -> None:
    render_page_title_with_help("🏠 Hauskonfigurator", _HELP, key="house_config_help")

    profiles_doc = load_house_profiles()
    profile_map = profiles_doc.get("profiles", {})
    profile_ids = sorted(profile_map.keys())
    selected_id = st.selectbox(
        "Profil",
        options=["— neu —", *profile_ids],
        key="house_profile_select",
    )

    existing = profile_map.get(selected_id, {}) if selected_id != "— neu —" else {}
    profile_id = st.text_input(
        "Profil-ID",
        value=existing.get("id", "mein_haushalt"),
        key="house_profile_id",
    )
    label = st.text_input(
        "Bezeichnung",
        value=existing.get("label", "Mein Haushalt"),
        key="house_profile_label",
    )
    annual_kwh = st.number_input(
        "Jahresverbrauch (kWh/a)",
        min_value=0.0,
        value=float(existing.get("annual_kwh", 4500.0)),
        step=100.0,
        key="house_annual_kwh",
    )

    st.subheader("Verbraucher")
    consumers = list(existing.get("consumers", []))
    consumer_count = st.number_input(
        "Anzahl Verbraucher",
        min_value=0,
        max_value=8,
        value=max(1, len(consumers)),
        step=1,
        key="house_consumer_count",
    )
    while len(consumers) < int(consumer_count):
        consumers.append(
            {
                "id": f"consumer_{len(consumers) + 1}",
                "label": f"Verbraucher {len(consumers) + 1}",
                "type": "generic",
                "nominal_power_kw": 2.0,
                "annual_kwh": 500.0,
            }
        )
    consumers = consumers[: int(consumer_count)]

    edited: list[dict] = []
    for index, consumer in enumerate(consumers):
        with st.expander(f"Verbraucher {index + 1}: {consumer.get('label', '')}", expanded=index == 0):
            c_id = st.text_input("ID", value=consumer.get("id", ""), key=f"hc_id_{index}")
            c_label = st.text_input(
                "Bezeichnung", value=consumer.get("label", ""), key=f"hc_label_{index}"
            )
            c_type = st.selectbox(
                "Typ",
                options=["generic", "thermal_annual"],
                index=0 if consumer.get("type") != "thermal_annual" else 1,
                key=f"hc_type_{index}",
            )
            nominal = st.number_input(
                "Nennleistung (kW)",
                min_value=0.0,
                value=float(consumer.get("nominal_power_kw", 0.0)),
                key=f"hc_nom_{index}",
            )
            item: dict = {
                "id": c_id,
                "label": c_label,
                "type": c_type,
                "nominal_power_kw": nominal,
            }
            if c_type == "generic":
                item["annual_kwh"] = st.number_input(
                    "Jahresenergie (kWh/a)",
                    min_value=0.0,
                    value=float(consumer.get("annual_kwh", 0.0)),
                    key=f"hc_kwh_{index}",
                )
                sched = consumer.get("schedule") or {}
                runs = st.number_input(
                    "Läufe pro Woche",
                    min_value=0,
                    value=int(sched.get("runs_per_week", 0)),
                    key=f"hc_runs_{index}",
                )
                if runs > 0:
                    item["schedule"] = {
                        "runs_per_week": runs,
                        "duration_h": float(sched.get("duration_h", 2.0)),
                        "start_flexibility": sched.get("start_flexibility", "day"),
                    }
            else:
                item["living_area_m2"] = st.number_input(
                    "Wohnfläche (m²)",
                    min_value=0.0,
                    value=float(consumer.get("living_area_m2", 120.0)),
                    key=f"hc_area_{index}",
                )
                item["building_class"] = st.selectbox(
                    "Gebäudeklasse",
                    options=[1, 2, 3, 4],
                    index=int(consumer.get("building_class", 3)) - 1,
                    key=f"hc_class_{index}",
                )
                item["heat_pump_type"] = st.selectbox(
                    "WP-Typ",
                    options=["luft", "erde"],
                    index=0 if consumer.get("heat_pump_type") != "erde" else 1,
                    key=f"hc_wp_{index}",
                )
                item["persons"] = st.number_input(
                    "Personen",
                    min_value=0,
                    value=int(consumer.get("persons", 2)),
                    key=f"hc_persons_{index}",
                )
            edited.append(item)

    preview = preview_baseload(annual_kwh, edited)
    st.metric("Verbraucher-Summe (kWh/a)", f"{preview['consumer_kwh']:.0f}")
    st.metric("Grundlast (kWh/a)", f"{preview['baseload_kwh']:.0f}")
    st.caption(
        f"Roh-Differenz {preview['raw_baseload_kwh']:.0f} kWh/a; "
        f"Untergrenze 5 % = {preview['baseload_min_kwh']:.0f} kWh/a"
    )

    if st.button("Profil speichern", type="primary", key="house_profile_save"):
        if not profile_id.strip():
            st.error("Profil-ID fehlt.")
        else:
            upsert_house_profile(
                {
                    "id": profile_id.strip(),
                    "label": label.strip() or profile_id.strip(),
                    "annual_kwh": float(annual_kwh),
                    "consumers": edited,
                }
            )
            st.success(f"Profil '{profile_id}' gespeichert.")
            st.rerun()
