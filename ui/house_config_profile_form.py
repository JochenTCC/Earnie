"""Hausprofil-Tab im Hauskonfigurator."""
from __future__ import annotations

import os

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
from runtime_store.persist_paths import resolve_house_profiles_json_path
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
_SESSION_FILE_STAMP_KEY = "house_profile_file_stamp"


def _scoped_key(session_scope: str, base: str) -> str:
    return f"{session_scope}__{base}"


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


def _render_generic_fields(
    consumer: dict,
    index: int,
    nominal: float,
    *,
    session_scope: str,
) -> dict:
    sched = consumer.get("schedule") or {}
    defaults = _schedule_defaults(sched)
    runs = st.number_input(
        "Läufe pro Woche",
        min_value=0,
        value=int(sched.get("runs_per_week", 0)),
        key=_scoped_key(session_scope, f"hc_runs_{index}"),
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
        key=_scoped_key(session_scope, f"hc_duration_{index}"),
    )
    start_hour = st.number_input(
        "Referenz-Startzeit (Stunde)",
        min_value=0,
        max_value=23,
        value=defaults["start_hour"],
        key=_scoped_key(session_scope, f"hc_start_{index}"),
    )
    start_shift_h = st.number_input(
        "Verschiebung (± h)",
        min_value=0.0,
        max_value=MAX_START_SHIFT_H,
        value=min(MAX_START_SHIFT_H, defaults["start_shift_h"]),
        step=0.5,
        key=_scoped_key(session_scope, f"hc_shift_{index}"),
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


def _flatten_consumer_for_edit(consumer: dict) -> dict:
    item = dict(consumer)
    thermal = item.pop("thermal", None)
    if isinstance(thermal, dict):
        for key, value in thermal.items():
            if key not in item and key not in {"latitude", "longitude"}:
                item[key] = value
    return item


def _consumers_from_existing(existing: dict) -> list[dict]:
    consumers = list(existing.get("consumers", []))
    if not consumers:
        return []
    return [_flatten_consumer_for_edit(consumer) for consumer in consumers]


def _profile_session_scope(selected_id: str, *, is_new: bool) -> str:
    return "__new__" if is_new else selected_id


def _house_profiles_file_stamp() -> str:
    path = resolve_house_profiles_json_path()
    try:
        return f"{os.path.abspath(path)}:{os.path.getmtime(path)}"
    except OSError:
        return os.path.abspath(path)


def _clear_scoped_widget_keys(session_scope: str) -> None:
    prefix = f"{session_scope}__"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            del st.session_state[key]


def _seed_profile_widget_state(session_scope: str, existing: dict) -> None:
    if existing:
        label = str(existing.get("label", "Mein Haushalt"))
        annual_kwh = float(existing.get("annual_kwh", 4500.0))
        latitude = float(existing.get("latitude", 48.2))
        longitude = float(existing.get("longitude", 11.0))
        default_pv_tilt = int(existing.get("default_pv_tilt", 25))
        default_pv_azimuth = int(existing.get("default_pv_azimuth", 0))
    else:
        label = "Mein Haushalt"
        annual_kwh = 4500.0
        latitude = 48.2
        longitude = 11.0
        default_pv_tilt = 25
        default_pv_azimuth = 0
    st.session_state[_scoped_key(session_scope, "house_profile_label")] = label
    st.session_state[_scoped_key(session_scope, "house_annual_kwh")] = annual_kwh
    st.session_state[_scoped_key(session_scope, "house_profile_latitude")] = latitude
    st.session_state[_scoped_key(session_scope, "house_profile_longitude")] = longitude
    st.session_state[_scoped_key(session_scope, "house_profile_default_pv_tilt")] = default_pv_tilt
    st.session_state[_scoped_key(session_scope, "house_profile_default_pv_azimuth")] = default_pv_azimuth


def _profile_widget_state_missing(session_scope: str) -> bool:
    """True when sync metadata exists but scoped widget keys were dropped (e.g. page navigation)."""
    return _scoped_key(session_scope, "house_profile_label") not in st.session_state


def _sync_profile_session(session_scope: str, existing: dict, *, file_stamp: str) -> list[dict]:
    scope_changed = st.session_state.get(_SESSION_SYNC_KEY) != session_scope
    file_changed = st.session_state.get(_SESSION_FILE_STAMP_KEY) != file_stamp
    widget_state_missing = _profile_widget_state_missing(session_scope)
    if scope_changed or file_changed or widget_state_missing:
        _clear_scoped_widget_keys(session_scope)
        _seed_profile_widget_state(session_scope, existing)
        st.session_state[_SESSION_SYNC_KEY] = session_scope
        st.session_state[_SESSION_FILE_STAMP_KEY] = file_stamp
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
    session_scope: str,
) -> dict:
    return {
        "car_available_from_hour": st.number_input(
            f"{prefix}: Ankunft ab (Stunde)",
            min_value=0,
            max_value=23,
            value=int(block.get("car_available_from_hour", 18)),
            key=_scoped_key(session_scope, f"hc_ev_{prefix}_from_{index}"),
        ),
        "ready_by_hour": st.number_input(
            f"{prefix}: Fertig bis (Stunde)",
            min_value=0,
            max_value=23,
            value=int(block.get("ready_by_hour", 7)),
            key=_scoped_key(session_scope, f"hc_ev_{prefix}_ready_{index}"),
        ),
        "daily_rest_soc": st.number_input(
            f"{prefix}: Rest-SOC (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(block.get("daily_rest_soc", 30.0)),
            step=1.0,
            key=_scoped_key(session_scope, f"hc_ev_{prefix}_soc_{index}"),
        ),
    }


def _render_ev_fields(consumer: dict, index: int, *, session_scope: str) -> dict:
    sched = dict(consumer.get("charging_schedule") or {})
    item: dict = {
        "min_power_kw": st.number_input(
            "Mindestleistung (kW)",
            min_value=0.0,
            value=float(consumer.get("min_power_kw", 1.4)),
            key=_scoped_key(session_scope, f"hc_ev_min_{index}"),
        ),
        "min_on_quarterhours": st.number_input(
            "Mindest-Ladedauer (Viertelstunden)",
            min_value=0,
            value=int(consumer.get("min_on_quarterhours", 4)),
            key=_scoped_key(session_scope, f"hc_ev_min_qh_{index}"),
        ),
        "battery_capacity_kwh": st.number_input(
            "Akkukapazität (kWh)",
            min_value=0.1,
            value=float(consumer.get("battery_capacity_kwh", 60.0)),
            step=1.0,
            key=_scoped_key(session_scope, f"hc_ev_cap_{index}"),
        ),
    }
    item["charging_schedule"] = {
        "target_soc_percent": st.number_input(
            "Ziel-SOC (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(sched.get("target_soc_percent", 100.0)),
            key=_scoped_key(session_scope, f"hc_ev_target_soc_{index}"),
        ),
        "charging_efficiency": st.number_input(
            "Lade-Wirkungsgrad",
            min_value=0.01,
            max_value=1.0,
            value=float(sched.get("charging_efficiency", 0.95)),
            step=0.01,
            key=_scoped_key(session_scope, f"hc_ev_eff_{index}"),
        ),
        "forecast_when_absent": st.checkbox(
            "Prognose bei Abwesenheit",
            value=bool(sched.get("forecast_when_absent", True)),
            key=_scoped_key(session_scope, f"hc_ev_forecast_{index}"),
        ),
        "weekday": _render_day_schedule(
            "Werktag",
            sched.get("weekday") or {},
            index=index,
            session_scope=session_scope,
        ),
        "weekend": _render_day_schedule(
            "Wochenende",
            sched.get("weekend") or {},
            index=index,
            session_scope=session_scope,
        ),
    }
    return item


def _inject_profile_geo(consumers: list[dict], latitude: float, longitude: float) -> list[dict]:
    enriched: list[dict] = []
    for consumer in consumers:
        item = dict(consumer)
        if item.get("type") == "thermal_annual":
            item = dict(item)
            item["latitude"] = latitude
            item["longitude"] = longitude
        enriched.append(item)
    return enriched


def _render_location_fields(*, session_scope: str) -> dict:
    st.subheader("Standort")
    col_a, col_b = st.columns(2)
    latitude = col_a.number_input(
        "Breitengrad",
        format="%.4f",
        key=_scoped_key(session_scope, "house_profile_latitude"),
    )
    longitude = col_b.number_input(
        "Längengrad",
        format="%.4f",
        key=_scoped_key(session_scope, "house_profile_longitude"),
    )
    try:
        from house_config.geo_timezone import lookup_timezone_name

        st.caption(
            f"Zeitzone (abgeleitet): **{lookup_timezone_name(float(latitude), float(longitude))}**"
        )
    except ValueError as exc:
        st.warning(str(exc))
    col_c, col_d = st.columns(2)
    default_pv_tilt = col_c.number_input(
        "PV-Default Neigung (°)",
        min_value=0,
        max_value=90,
        help="Vorschlag für neue PV-Anlage im Tab PV-Anlage (überschreibbar).",
        key=_scoped_key(session_scope, "house_profile_default_pv_tilt"),
    )
    default_pv_azimuth = col_d.number_input(
        "PV-Default Azimut (°)",
        min_value=-180,
        max_value=180,
        help="0 = Süd, -90 = Ost, 90 = West. Überschreibbar im Tab PV-Anlage.",
        key=_scoped_key(session_scope, "house_profile_default_pv_azimuth"),
    )
    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "default_pv_tilt": float(default_pv_tilt),
        "default_pv_azimuth": float(default_pv_azimuth),
    }


def _render_thermal_solar_fields(
    thermal: dict,
    index: int,
    *,
    session_scope: str,
    default_tilt: float = 18.0,
    default_azimuth: float = 0.0,
) -> dict:
    tilt_fallback = int(thermal.get("solar_thermal_tilt_deg", default_tilt))
    azimuth_fallback = int(thermal.get("solar_thermal_azimuth_deg", default_azimuth))
    return {
        "solar_thermal_area_m2": st.number_input(
            "Solar-Kollektor Fläche (m²)",
            min_value=0.0,
            value=float(thermal.get("solar_thermal_area_m2", 0.0) or 0.0),
            step=1.0,
            key=_scoped_key(session_scope, f"hc_solar_area_{index}"),
        ),
        "solar_thermal_tilt_deg": st.number_input(
            "Solar-Kollektor Neigung (°)",
            min_value=0,
            max_value=90,
            value=tilt_fallback,
            key=_scoped_key(session_scope, f"hc_solar_tilt_{index}"),
        ),
        "solar_thermal_azimuth_deg": st.number_input(
            "Solar-Kollektor Azimut (°)",
            min_value=-180,
            max_value=180,
            value=azimuth_fallback,
            help="0 = Süd, -90 = Ost, 90 = West",
            key=_scoped_key(session_scope, f"hc_solar_azimuth_{index}"),
        ),
    }


def _render_consumer_form(
    consumer: dict,
    index: int,
    *,
    latitude: float,
    longitude: float,
    session_scope: str,
    default_pv_tilt: float = 18.0,
    default_pv_azimuth: float = 0.0,
) -> dict:
    title = consumer.get("label") or f"Verbraucher {index + 1}"
    with st.expander(f"Verbraucher {index + 1}: {title}", expanded=index == 0):
        cols = st.columns([5, 1])
        with cols[1]:
            if st.button("Entfernen", key=_scoped_key(session_scope, f"hc_remove_{index}")):
                consumers = list(st.session_state[_SESSION_CONSUMERS_KEY])
                del consumers[index]
                st.session_state[_SESSION_CONSUMERS_KEY] = consumers
                st.rerun()

        type_options = _consumer_type_options(index)
        current_type = str(consumer.get("type", "generic"))
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
            key=_scoped_key(session_scope, f"hc_type_{index}"),
        )
        c_label = st.text_input(
            "Bezeichnung", value=consumer.get("label", ""), key=_scoped_key(session_scope, f"hc_label_{index}")
        )
        if consumer.get("id"):
            st.caption(f"Verbraucher-ID: `{consumer['id']}`")
        nominal = st.number_input(
            "Nennleistung (kW)",
            min_value=0.0,
            value=float(consumer.get("nominal_power_kw", 0.0)),
            key=_scoped_key(session_scope, f"hc_nom_{index}"),
        )
        item: dict = {
            "label": c_label,
            "type": c_type,
            "nominal_power_kw": nominal,
        }
        if c_type == "generic":
            generic_fields = _render_generic_fields(
                consumer, index, nominal, session_scope=session_scope
            )
            item.update(generic_fields)
        elif c_type == "ev":
            item.update(_render_ev_fields(consumer, index, session_scope=session_scope))
        else:
            thermal = consumer.get("thermal") or consumer
            item["living_area_m2"] = st.number_input(
                "Wohnfläche (m²)",
                min_value=0.0,
                value=float(thermal.get("living_area_m2", 120.0)),
                key=_scoped_key(session_scope, f"hc_area_{index}"),
            )
            building_class = int(thermal.get("building_class", 3))
            item["building_class"] = st.selectbox(
                "Gebäudeklasse",
                options=[1, 2, 3, 4],
                index=max(0, min(3, building_class - 1)),
                format_func=building_class_option_label,
                key=_scoped_key(session_scope, f"hc_class_{index}"),
            )
            use_exact_hwb = st.checkbox(
                "Genaue HWB-Angabe",
                value=bool(float(thermal.get("hwb_kwh_m2", 0.0) or 0.0) > 0),
                key=_scoped_key(session_scope, f"hc_hwb_use_{index}"),
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
                    key=_scoped_key(session_scope, f"hc_hwb_{index}"),
                )
            item["heat_pump_type"] = st.selectbox(
                "WP-Typ",
                options=["luft", "erde"],
                index=0 if thermal.get("heat_pump_type") != "erde" else 1,
                key=_scoped_key(session_scope, f"hc_wp_{index}"),
            )
            item["persons"] = st.number_input(
                "Personen",
                min_value=0,
                value=int(thermal.get("persons", 2)),
                key=_scoped_key(session_scope, f"hc_persons_{index}"),
            )
            item.update(
                _render_thermal_solar_fields(
                    thermal,
                    index,
                    session_scope=session_scope,
                    default_tilt=default_pv_tilt,
                    default_azimuth=default_pv_azimuth,
                )
            )
            from data.modeled_climate import thermal_annual_kwh_from_archive

            thermal_preview = {**item, "latitude": latitude, "longitude": longitude}
            wp_annual, ref_year = thermal_annual_kwh_from_archive(
                thermal_preview,
                house_profile={
                    "latitude": latitude,
                    "longitude": longitude,
                    "default_pv_tilt": default_pv_tilt,
                    "default_pv_azimuth": default_pv_azimuth,
                },
            )
            st.metric("Geschätzter WP-Jahresbedarf (kWh/a)", f"{wp_annual:.0f}")
            st.caption(
                f"Basis: Open-Meteo-Archiv {ref_year} "
                f"({latitude:.4f}°N, {longitude:.4f}°E)"
            )
    return item


def _apply_pending_profile_select() -> None:
    pending = st.session_state.pop(_SESSION_SELECT_PENDING_KEY, None)
    if pending is not None:
        st.session_state["house_profile_select"] = pending


def _initial_profile_index(profile_ids: list[str]) -> int | None:
    if "house_profile_select" in st.session_state:
        return None
    from ui.house_config_io import get_runtime_scenario_refs

    profile_id = str(get_runtime_scenario_refs().get("house_profile_id", "") or "").strip()
    if profile_id in profile_ids:
        return profile_ids.index(profile_id) + 1
    return None


def _render_modeled_consumption_section(
    *,
    preview_id: str,
    annual_kwh: float,
    resolved: list[dict],
    preview: dict,
) -> None:
    from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display

    modeled_profile = {
        "annual_kwh": annual_kwh,
        "baseload_kwh": preview["baseload_kwh"],
        "consumers": resolved,
    }
    reset_token = (
        f"{preview_id}:{annual_kwh:.0f}:{preview['consumer_kwh']:.0f}:"
        f"{preview['baseload_kwh']:.0f}"
    )
    st.subheader("Verbrauchsprofil (Modell)")
    st.caption("Modelliertes Hausprofil — ohne Ist-CSV und ohne cons_data.")
    render_consumption_display(
        ConsumptionDisplayMode.MODELED_PROFILE,
        key_prefix=f"house_profile_model_{preview_id}",
        profile=modeled_profile,
        reset_token=reset_token,
    )


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
        modeled_profile = {
            "annual_kwh": annual_kwh,
            "baseload_kwh": preview["baseload_kwh"],
            "consumers": resolved,
        }
        series = load_hourly_profile_csv(active_path)
        from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display

        render_consumption_display(
            ConsumptionDisplayMode.CSV_VALIDATION,
            key_prefix=f"house_profile_csv_{preview_id}",
            profile=modeled_profile,
            csv_series=series,
            annual_kwh=float(annual_kwh),
            reset_token=active_path,
        )
    except (ValueError, OSError) as exc:
        st.error(f"CSV konnte nicht ausgewertet werden: {exc}")


def render_house_profile_tab() -> None:
    _apply_pending_profile_select()
    profiles_doc = load_house_profiles()
    profile_map = profiles_doc.get("profiles", {})
    profile_ids = sorted(profile_map.keys())
    profile_options = ["— neu —", *profile_ids]
    initial_index = _initial_profile_index(profile_ids)
    if initial_index is not None:
        selected_id = st.selectbox(
            "Profil",
            options=profile_options,
            index=initial_index,
            key="house_profile_select",
        )
    else:
        selected_id = st.selectbox(
            "Profil",
            options=profile_options,
            key="house_profile_select",
        )
    is_new = selected_id == "— neu —"
    existing = profile_map.get(selected_id, {}) if not is_new else {}
    stable_profile_id = str(existing.get("id", "")).strip()
    session_scope = _profile_session_scope(selected_id, is_new=is_new)
    file_stamp = _house_profiles_file_stamp()
    _sync_profile_session(session_scope, existing, file_stamp=file_stamp)

    label = st.text_input(
        "Bezeichnung",
        key=_scoped_key(session_scope, "house_profile_label"),
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
        step=100.0,
        key=_scoped_key(session_scope, "house_annual_kwh"),
    )

    location = _render_location_fields(session_scope=session_scope)

    st.subheader("Verbraucher")
    st.caption(
        "Optional — ohne Verbraucher gilt der gesamte Jahresverbrauch als Grundlast. "
        "„Haus Wärme“ ist nicht erforderlich."
    )
    consumers = list(st.session_state.get(_SESSION_CONSUMERS_KEY, []))
    if st.button("Verbraucher hinzufügen", key=_scoped_key(session_scope, "house_consumer_add")):
        st.session_state[_SESSION_CONSUMERS_KEY].append(_default_additional_consumer())
        st.rerun()

    edited = [
        _render_consumer_form(
            consumer,
            index,
            latitude=location["latitude"],
            longitude=location["longitude"],
            session_scope=session_scope,
            default_pv_tilt=location["default_pv_tilt"],
            default_pv_azimuth=location["default_pv_azimuth"],
        )
        for index, consumer in enumerate(consumers)
    ]
    resolved = _resolve_consumer_ids(consumers, edited)
    resolved_for_preview = _inject_profile_geo(
        resolved,
        location["latitude"],
        location["longitude"],
    )
    preview = preview_baseload(annual_kwh, resolved_for_preview)
    st.metric("Verbraucher-Summe (kWh/a)", f"{preview['consumer_kwh']:.0f}")
    st.metric("Grundlast (kWh/a)", f"{preview['baseload_kwh']:.0f}")
    st.caption(
        f"Roh-Differenz {preview['raw_baseload_kwh']:.0f} kWh/a; "
        f"Untergrenze 5 % = {preview['baseload_min_kwh']:.0f} kWh/a"
    )

    _render_modeled_consumption_section(
        preview_id=preview_id,
        annual_kwh=float(annual_kwh),
        resolved=resolved_for_preview,
        preview=preview,
    )

    _render_consumption_csv_section(
        existing=existing,
        preview_id=preview_id,
        annual_kwh=float(annual_kwh),
        resolved=resolved_for_preview,
        preview=preview,
    )

    if st.button("Profil speichern", type="primary", key=_scoped_key(session_scope, "house_profile_save")):
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
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "default_pv_tilt": location["default_pv_tilt"],
                "default_pv_azimuth": location["default_pv_azimuth"],
                "consumers": resolved,
                "total_profile_csv": st.session_state.get(
                    f"house_profile_csv_path_{preview_id}",
                    existing.get("total_profile_csv", ""),
                ),
            }
        )
        saved_profile = load_house_profiles().get("profiles", {}).get(profile_id, {})
        st.session_state[_SESSION_SELECT_PENDING_KEY] = profile_id
        st.session_state[_SESSION_FILE_STAMP_KEY] = _house_profiles_file_stamp()
        st.session_state[_SESSION_SYNC_KEY] = None
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(saved_profile)
        st.success(f"Profil '{profile_id}' gespeichert.")
        st.rerun()
