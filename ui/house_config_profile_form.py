"""Hausprofil-Tab im Hauskonfigurator."""
from __future__ import annotations

import streamlit as st

from house_config.id_slug import slug_id
from house_config.thermal_labels import (
    CONSUMER_TYPE_LABELS,
    building_class_option_label,
)
from ui.house_config_io import load_house_profiles, preview_baseload, upsert_house_profile


def _resolve_profile_id(
    *,
    is_new: bool,
    existing_id: str,
    label: str,
    profile_ids: set[str],
) -> str:
    if not is_new and existing_id:
        return existing_id
    others = set(profile_ids)
    return slug_id(label, existing=others)


def _resolve_consumer_ids(consumers: list[dict], edited: list[dict]) -> list[dict]:
    taken: set[str] = set()
    resolved: list[dict] = []
    for original, item in zip(consumers, edited):
        label = str(item.get("label", "")).strip()
        stable_id = str(original.get("id", "")).strip()
        if stable_id:
            consumer_id = stable_id
        else:
            consumer_id = slug_id(label or "verbraucher", existing=taken)
        item = dict(item)
        item["id"] = consumer_id
        item["label"] = label or consumer_id
        taken.add(consumer_id)
        resolved.append(item)
    return resolved


def render_house_profile_tab() -> None:
    profiles_doc = load_house_profiles()
    profile_map = profiles_doc.get("profiles", {})
    profile_ids = sorted(profile_map.keys())
    selected_id = st.selectbox(
        "Profil",
        options=["— neu —", *profile_ids],
        key="house_profile_select",
    )
    is_new = selected_id == "— neu —"
    existing = profile_map.get(selected_id, {}) if not is_new else {}
    stable_profile_id = str(existing.get("id", "")).strip()

    label = st.text_input(
        "Bezeichnung",
        value=existing.get("label", "Mein Haushalt"),
        key="house_profile_label",
    )
    preview_id = _resolve_profile_id(
        is_new=is_new,
        existing_id=stable_profile_id,
        label=label,
        profile_ids=set(profile_ids),
    )
    st.caption(f"Profil-ID: `{preview_id}`")

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
                "label": f"Verbraucher {len(consumers) + 1}",
                "type": "generic",
                "nominal_power_kw": 2.0,
                "annual_kwh": 500.0,
            }
        )
    consumers = consumers[: int(consumer_count)]

    edited: list[dict] = []
    for index, consumer in enumerate(consumers):
        title = consumer.get("label") or f"Verbraucher {index + 1}"
        with st.expander(f"Verbraucher {index + 1}: {title}", expanded=index == 0):
            c_label = st.text_input(
                "Bezeichnung", value=consumer.get("label", ""), key=f"hc_label_{index}"
            )
            if consumer.get("id"):
                st.caption(f"Verbraucher-ID: `{consumer['id']}`")
            c_type = st.selectbox(
                "Typ",
                options=["generic", "thermal_annual"],
                index=0 if consumer.get("type") != "thermal_annual" else 1,
                format_func=lambda value: CONSUMER_TYPE_LABELS.get(value, value),
                key=f"hc_type_{index}",
            )
            nominal = st.number_input(
                "Nennleistung (kW)",
                min_value=0.0,
                value=float(consumer.get("nominal_power_kw", 0.0)),
                key=f"hc_nom_{index}",
            )
            item: dict = {
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
                thermal = consumer.get("thermal") or consumer
                item["living_area_m2"] = st.number_input(
                    "Wohnfläche (m²)",
                    min_value=0.0,
                    value=float(thermal.get("living_area_m2", 120.0)),
                    key=f"hc_area_{index}",
                )
                building_class = int(thermal.get("building_class", 3))
                item["building_class"] = st.selectbox(
                    "Gebäudeklasse",
                    options=[1, 2, 3, 4],
                    index=max(0, min(3, building_class - 1)),
                    format_func=building_class_option_label,
                    key=f"hc_class_{index}",
                )
                use_exact_hwb = st.checkbox(
                    "Genaue HWB-Angabe",
                    value=bool(float(thermal.get("hwb_kwh_m2", 0.0) or 0.0) > 0),
                    key=f"hc_hwb_use_{index}",
                )
                if use_exact_hwb:
                    from data.heating_need import specific_heating_kwh_m2

                    default_hwb = float(thermal.get("hwb_kwh_m2", 0.0) or 0.0)
                    if default_hwb <= 0:
                        default_hwb = specific_heating_kwh_m2(int(item["building_class"]))
                    item["hwb_kwh_m2"] = st.number_input(
                        "HWB (kWh/m²a)",
                        min_value=0.1,
                        value=default_hwb,
                        step=1.0,
                        key=f"hc_hwb_{index}",
                    )
                item["heat_pump_type"] = st.selectbox(
                    "WP-Typ",
                    options=["luft", "erde"],
                    index=0 if thermal.get("heat_pump_type") != "erde" else 1,
                    key=f"hc_wp_{index}",
                )
                item["persons"] = st.number_input(
                    "Personen",
                    min_value=0,
                    value=int(thermal.get("persons", 2)),
                    key=f"hc_persons_{index}",
                )
            edited.append(item)

    resolved = _resolve_consumer_ids(consumers, edited)
    preview = preview_baseload(annual_kwh, resolved)
    st.metric("Verbraucher-Summe (kWh/a)", f"{preview['consumer_kwh']:.0f}")
    st.metric("Grundlast (kWh/a)", f"{preview['baseload_kwh']:.0f}")
    st.caption(
        f"Roh-Differenz {preview['raw_baseload_kwh']:.0f} kWh/a; "
        f"Untergrenze 5 % = {preview['baseload_min_kwh']:.0f} kWh/a"
    )

    if st.button("Profil speichern", type="primary", key="house_profile_save"):
        profile_id = _resolve_profile_id(
            is_new=is_new,
            existing_id=stable_profile_id,
            label=label,
            profile_ids=set(profile_ids),
        )
        upsert_house_profile(
            {
                "id": profile_id,
                "label": label.strip() or profile_id,
                "annual_kwh": float(annual_kwh),
                "consumers": resolved,
            }
        )
        st.success(f"Profil '{profile_id}' gespeichert.")
        st.rerun()
