"""Hausprofil-Tab im Hauskonfigurator."""
from __future__ import annotations

import streamlit as st

from house_config.generic_schedule import (
    DEFAULT_START_HOUR,
    MAX_START_SHIFT_H,
    format_start_window_caption,
    generic_annual_kwh,
    migrate_start_flexibility,
)
from house_config.id_slug import slug_id
from house_config.thermal_labels import (
    CONSUMER_TYPE_LABELS,
    building_class_option_label,
)
from ui.house_config_io import (
    load_house_profiles,
    preview_baseload,
    save_profile_consumption_csv,
    upsert_house_profile,
)

CONSUMER_TYPE_OPTIONS = ["generic", "thermal_annual", "ev"]
_SESSION_SYNC_KEY = "house_profile_sync_id"
_SESSION_CONSUMERS_KEY = "house_profile_consumers"
_SESSION_SELECT_PENDING_KEY = "house_profile_select_pending"


def _default_consumer() -> dict:
    return {
        "label": "Haus Wärme",
        "type": "thermal_annual",
        "nominal_power_kw": 3.5,
        "living_area_m2": 120.0,
        "building_class": 3,
        "heat_pump_type": "luft",
        "persons": 2,
    }


def _default_additional_consumer() -> dict:
    return {
        "label": "Verbraucher",
        "type": "generic",
        "nominal_power_kw": 1.0,
        "schedule": {
            "runs_per_week": 0,
        },
    }


def _schedule_defaults(sched: dict) -> dict:
    migrated = migrate_start_flexibility(dict(sched))
    return {
        "duration_h": float(migrated.get("duration_h", 2.0) or 2.0),
        "start_hour": int(migrated.get("start_hour", DEFAULT_START_HOUR)) % 24,
        "start_shift_h": float(migrated.get("start_shift_h", 12.0) or 12.0),
    }


def _render_generic_fields(consumer: dict, index: int, nominal: float) -> dict:
    sched = consumer.get("schedule") or {}
    defaults = _schedule_defaults(sched)
    runs = st.number_input(
        "Läufe pro Woche",
        min_value=0,
        value=int(sched.get("runs_per_week", 0)),
        key=f"hc_runs_{index}",
    )
    item: dict = {
        "nominal_power_kw": nominal,
        "schedule": None,
    }
    if runs <= 0:
        item["annual_kwh"] = 0.0
        return item
    duration_h = st.number_input(
        "Nenndauer pro Lauf (h)",
        min_value=0.1,
        value=defaults["duration_h"],
        step=0.25,
        key=f"hc_duration_{index}",
    )
    start_hour = st.number_input(
        "Referenz-Startzeit (Stunde)",
        min_value=0,
        max_value=23,
        value=defaults["start_hour"],
        key=f"hc_start_{index}",
    )
    start_shift_h = st.number_input(
        "Verschiebung (± h)",
        min_value=0.0,
        max_value=MAX_START_SHIFT_H,
        value=min(MAX_START_SHIFT_H, defaults["start_shift_h"]),
        step=0.5,
        key=f"hc_shift_{index}",
    )
    st.caption(format_start_window_caption(int(start_hour), float(start_shift_h)))
    st.caption("Bei 12 h Verschiebung ist der Startzeitpunkt vollständig frei.")
    item["schedule"] = {
        "runs_per_week": runs,
        "duration_h": float(duration_h),
        "start_hour": int(start_hour) % 24,
        "start_shift_h": float(start_shift_h),
    }
    preview_consumer = {
        "type": "generic",
        "nominal_power_kw": nominal,
        "schedule": item["schedule"],
    }
    item["annual_kwh"] = generic_annual_kwh(preview_consumer)
    st.metric("Jahresenergie (kWh/a)", f"{item['annual_kwh']:.0f}")
    return item


def _default_ev_consumer() -> dict:
    return {
        "label": "E-Auto",
        "type": "ev",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "min_on_quarterhours": 4,
        "battery_capacity_kwh": 60.0,
        "charging_schedule": {
            "target_soc_percent": 100.0,
            "charging_efficiency": 0.95,
            "forecast_when_absent": True,
            "weekday": {
                "car_available_from_hour": 18,
                "ready_by_hour": 7,
                "daily_rest_soc": 40.0,
            },
            "weekend": {
                "car_available_from_hour": 20,
                "ready_by_hour": 9,
                "daily_rest_soc": 30.0,
            },
        },
    }


def _consumers_from_existing(existing: dict) -> list[dict]:
    consumers = list(existing.get("consumers", []))
    if not consumers:
        return [_default_consumer()]
    return [dict(consumer) for consumer in consumers]


def _profile_session_scope(selected_id: str, *, is_new: bool) -> str:
    return "__new__" if is_new else selected_id


def _sync_consumers_session(session_scope: str, existing: dict) -> list[dict]:
    if st.session_state.get(_SESSION_SYNC_KEY) != session_scope:
        st.session_state[_SESSION_SYNC_KEY] = session_scope
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(existing)
    return list(st.session_state.get(_SESSION_CONSUMERS_KEY, []))


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
    for index, item in enumerate(edited):
        label = str(item.get("label", "")).strip()
        original = consumers[index] if index < len(consumers) else {}
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


def _consumer_type_options(consumer_index: int) -> list[str]:
    if consumer_index == 0:
        return list(CONSUMER_TYPE_OPTIONS)
    return [value for value in CONSUMER_TYPE_OPTIONS if value != "thermal_annual"]


def _type_index(consumer_type: str, options: list[str]) -> int:
    try:
        return options.index(consumer_type)
    except ValueError:
        return 0


def _render_day_schedule(
    prefix: str,
    block: dict,
    *,
    index: int,
) -> dict:
    return {
        "car_available_from_hour": st.number_input(
            f"{prefix}: Ankunft ab (Stunde)",
            min_value=0,
            max_value=23,
            value=int(block.get("car_available_from_hour", 18)),
            key=f"hc_ev_{prefix}_from_{index}",
        ),
        "ready_by_hour": st.number_input(
            f"{prefix}: Fertig bis (Stunde)",
            min_value=0,
            max_value=23,
            value=int(block.get("ready_by_hour", 7)),
            key=f"hc_ev_{prefix}_ready_{index}",
        ),
        "daily_rest_soc": st.number_input(
            f"{prefix}: Rest-SOC (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(block.get("daily_rest_soc", 30.0)),
            step=1.0,
            key=f"hc_ev_{prefix}_soc_{index}",
        ),
    }


def _render_ev_fields(consumer: dict, index: int) -> dict:
    sched = dict(consumer.get("charging_schedule") or {})
    item: dict = {
        "min_power_kw": st.number_input(
            "Mindestleistung (kW)",
            min_value=0.0,
            value=float(consumer.get("min_power_kw", 1.4)),
            key=f"hc_ev_min_{index}",
        ),
        "min_on_quarterhours": st.number_input(
            "Mindest-Ladedauer (Viertelstunden)",
            min_value=0,
            value=int(consumer.get("min_on_quarterhours", 4)),
            key=f"hc_ev_min_qh_{index}",
        ),
        "battery_capacity_kwh": st.number_input(
            "Akkukapazität (kWh)",
            min_value=0.1,
            value=float(consumer.get("battery_capacity_kwh", 60.0)),
            step=1.0,
            key=f"hc_ev_cap_{index}",
        ),
    }
    item["charging_schedule"] = {
        "target_soc_percent": st.number_input(
            "Ziel-SOC (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(sched.get("target_soc_percent", 100.0)),
            key=f"hc_ev_target_soc_{index}",
        ),
        "charging_efficiency": st.number_input(
            "Lade-Wirkungsgrad",
            min_value=0.01,
            max_value=1.0,
            value=float(sched.get("charging_efficiency", 0.95)),
            step=0.01,
            key=f"hc_ev_eff_{index}",
        ),
        "forecast_when_absent": st.checkbox(
            "Prognose bei Abwesenheit",
            value=bool(sched.get("forecast_when_absent", True)),
            key=f"hc_ev_forecast_{index}",
        ),
        "weekday": _render_day_schedule(
            "Werktag",
            sched.get("weekday") or {},
            index=index,
        ),
        "weekend": _render_day_schedule(
            "Wochenende",
            sched.get("weekend") or {},
            index=index,
        ),
    }
    return item


def _render_consumer_form(consumer: dict, index: int) -> dict:
    title = consumer.get("label") or f"Verbraucher {index + 1}"
    with st.expander(f"Verbraucher {index + 1}: {title}", expanded=index == 0):
        cols = st.columns([5, 1])
        with cols[1]:
            if st.button("Entfernen", key=f"hc_remove_{index}"):
                consumers = list(st.session_state[_SESSION_CONSUMERS_KEY])
                if len(consumers) > 1:
                    del consumers[index]
                    st.session_state[_SESSION_CONSUMERS_KEY] = consumers
                    st.rerun()
                else:
                    st.warning("Mindestens ein Verbraucher erforderlich.")

        type_options = _consumer_type_options(index)
        current_type = str(consumer.get("type", "thermal_annual"))
        if index > 0 and current_type == "thermal_annual":
            st.warning(
                "Typ „Haus Wärme“ ist nur für Verbraucher 1 erlaubt. "
                "Bitte einen anderen Typ wählen."
            )
        c_type = st.selectbox(
            "Typ",
            options=type_options,
            index=_type_index(current_type, type_options),
            format_func=lambda value: CONSUMER_TYPE_LABELS.get(value, value),
            key=f"hc_type_{index}",
        )
        c_label = st.text_input(
            "Bezeichnung", value=consumer.get("label", ""), key=f"hc_label_{index}"
        )
        if consumer.get("id"):
            st.caption(f"Verbraucher-ID: `{consumer['id']}`")
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
            generic_fields = _render_generic_fields(consumer, index, nominal)
            item.update(generic_fields)
        elif c_type == "ev":
            item.update(_render_ev_fields(consumer, index))
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
    return item


def _apply_pending_profile_select() -> None:
    pending = st.session_state.pop(_SESSION_SELECT_PENDING_KEY, None)
    if pending is not None:
        st.session_state["house_profile_select"] = pending


def _render_consumption_csv_section(
    *,
    existing: dict,
    preview_id: str,
    annual_kwh: float,
    resolved: list[dict],
    preview: dict,
) -> None:
    from pathlib import Path

    from house_config.consumption_csv import load_hourly_profile_csv
    from ui.consumption_validation_charts import (
        load_csv_monthly_kwh,
        modeled_monthly_kwh,
        monthly_comparison_chart,
        timeseries_comparison_chart,
    )

    st.subheader("Jahres-Verbrauchs-CSV (optional)")
    st.caption(
        "Format: `timestamp;power_kw` (stündlich). "
        "Zum Abgleich Ist-Verbrauch vs. modellierte Konfiguration."
    )

    session_key = f"house_profile_csv_path_{preview_id}"
    if session_key not in st.session_state:
        st.session_state[session_key] = str(existing.get("total_profile_csv", "") or "").strip()

    csv_path = st.text_input(
        "CSV-Pfad",
        value=st.session_state[session_key],
        key=f"house_profile_csv_input_{preview_id}",
        help="Relativer Pfad, z. B. config/uploads/mein_haushalt_verbrauch.csv",
    )
    st.session_state[session_key] = csv_path.strip()

    upload = st.file_uploader(
        "CSV hochladen",
        type=["csv"],
        key=f"house_profile_csv_upload_{preview_id}",
    )
    if upload is not None:
        try:
            saved_path = save_profile_consumption_csv(
                preview_id,
                upload.getvalue(),
                upload.name,
            )
            load_hourly_profile_csv(saved_path)
            st.session_state[session_key] = saved_path
            st.success(f"CSV gespeichert: `{saved_path}`")
        except (ValueError, OSError) as exc:
            st.error(f"CSV ungültig: {exc}")

    if st.button("CSV-Zuordnung entfernen", key=f"house_profile_csv_clear_{preview_id}"):
        st.session_state[session_key] = ""
        st.rerun()

    active_path = st.session_state[session_key]
    if not active_path:
        return
    if not Path(active_path).is_file():
        st.warning(f"Datei nicht gefunden: `{active_path}`")
        return

    try:
        actual_monthly = load_csv_monthly_kwh(active_path)
        modeled_profile = {
            "annual_kwh": annual_kwh,
            "baseload_kwh": preview["baseload_kwh"],
            "consumers": resolved,
        }
        model_monthly = modeled_monthly_kwh(modeled_profile)
        actual_total = sum(actual_monthly.values())
        model_total = sum(model_monthly.values())
        col_a, col_b = st.columns(2)
        col_a.metric("Ist-Jahresverbrauch (CSV)", f"{actual_total:.0f} kWh")
        col_b.metric("Modell-Jahresverbrauch", f"{model_total:.0f} kWh")
        if annual_kwh > 0 and abs(actual_total - annual_kwh) / annual_kwh > 0.15:
            st.info(
                f"Hinweis: Konfigurierter Jahresverbrauch ({annual_kwh:.0f} kWh) "
                f"weicht vom CSV ({actual_total:.0f} kWh) ab."
            )
        st.plotly_chart(monthly_comparison_chart(actual_monthly, model_monthly), width="stretch")
        st.plotly_chart(
            timeseries_comparison_chart(active_path, modeled_profile),
            width="stretch",
        )
    except (ValueError, OSError) as exc:
        st.error(f"CSV konnte nicht ausgewertet werden: {exc}")


def render_house_profile_tab() -> None:
    _apply_pending_profile_select()
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
    session_scope = _profile_session_scope(selected_id, is_new=is_new)
    consumers = _sync_consumers_session(session_scope, existing)
    if st.button("Verbraucher hinzufügen", key="house_consumer_add"):
        st.session_state[_SESSION_CONSUMERS_KEY].append(_default_additional_consumer())
        st.rerun()

    edited = [_render_consumer_form(consumer, index) for index, consumer in enumerate(consumers)]
    resolved = _resolve_consumer_ids(consumers, edited)
    preview = preview_baseload(annual_kwh, resolved)
    st.metric("Verbraucher-Summe (kWh/a)", f"{preview['consumer_kwh']:.0f}")
    st.metric("Grundlast (kWh/a)", f"{preview['baseload_kwh']:.0f}")
    st.caption(
        f"Roh-Differenz {preview['raw_baseload_kwh']:.0f} kWh/a; "
        f"Untergrenze 5 % = {preview['baseload_min_kwh']:.0f} kWh/a"
    )

    _render_consumption_csv_section(
        existing=existing,
        preview_id=preview_id,
        annual_kwh=float(annual_kwh),
        resolved=resolved,
        preview=preview,
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
                "total_profile_csv": st.session_state.get(
                    f"house_profile_csv_path_{preview_id}",
                    existing.get("total_profile_csv", ""),
                ),
            }
        )
        saved_profile = load_house_profiles().get("profiles", {}).get(profile_id, {})
        st.session_state[_SESSION_SELECT_PENDING_KEY] = profile_id
        st.session_state[_SESSION_SYNC_KEY] = profile_id
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(saved_profile)
        st.success(f"Profil '{profile_id}' gespeichert.")
        st.rerun()
