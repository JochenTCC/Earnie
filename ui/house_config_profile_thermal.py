"""Location / thermal consumer fields for Hausprofil form."""
from __future__ import annotations

from ui.house_config_profile_session import _live_markers_enabled, _scoped_key

import os

import streamlit as st

from house_config.earnie_role import (
    DEFAULT_MANUAL_HORIZON_H,
    EARNIE_ROLE_FLEX,
    EARNIE_ROLE_KNOWN,
    EARNIE_ROLE_MANUAL,
    resolve_earnie_role,
)
from house_config.generic_schedule import (
    DEFAULT_START_HOUR,
    MAX_START_SHIFT_H,
    format_start_window_caption,
    generic_annual_kwh,
    reject_legacy_start_flexibility,
)
from house_config.id_slug import slug_id
from house_config.thermal_labels import (
    CONSUMER_TYPE_LABELS,
    building_class_option_label,
)
from runtime_store.persist_paths import resolve_house_profiles_json_path
from ui.house_config_io import (
    apply_csv_path_pending,
    csv_upload_widget_key,
    load_house_profiles,
    preview_baseload,
    queue_csv_path_update,
    save_profile_consumption_csv,
    single_csv_upload,
    upsert_house_profile,
)
from ui.auto_persist import auto_persist
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
    labeled_checkbox,
    labeled_number_input,
    labeled_selectbox,
    labeled_text_input,
)


_PASSTHROUGH_CONSUMER_KEYS = (
    "loxone_inputs",
    "loxone_outputs",
    "optimizer_flex",
    "thermal_flex_window",
    "max_on_quarterhours",
    "max_pulses_per_day",
    "min_on_quarterhours",
    "heating_power_threshold_kw",
    "actual_temp_step_c",
    "thermal_control",
    "filter_schedule",
    "daily_target_source",
    "daily_target_kwh",
    "profile_csv",
    "use_profile_csv",
    "ehal_bindings",
)




def _inject_profile_geo(
    consumers: list[dict],
    latitude: float,
    longitude: float,
    *,
    timezone_name: str | None = None,
) -> list[dict]:
    enriched: list[dict] = []
    for consumer in consumers:
        item = dict(consumer)
        if item.get("type") == "thermal_annual":
            item = dict(item)
            item["latitude"] = latitude
            item["longitude"] = longitude
        elif item.get("type") == "thermal_rc":
            rc = dict(item.get("thermal_rc") or {})
            rc["latitude"] = latitude
            rc["longitude"] = longitude
            if timezone_name:
                rc["timezone_name"] = timezone_name
            item["thermal_rc"] = rc
        enriched.append(item)
    return enriched

def _render_location_fields(*, session_scope: str) -> dict:
    st.subheader("Standort")
    land_key = _scoped_key(session_scope, "house_profile_land")
    if land_key not in st.session_state:
        st.session_state[land_key] = "AT"
    elif st.session_state[land_key] not in {"AT", "DE", "CH"}:
        st.session_state[land_key] = "AT"
    col_lat, col_lon, col_land = st.columns(3)
    with col_lat:
        latitude = labeled_number_input(
            "Breitengrad",
            format="%.4f",
            key=_scoped_key(session_scope, "house_profile_latitude"),
        )
    with col_lon:
        longitude = labeled_number_input(
            "Längengrad",
            format="%.4f",
            key=_scoped_key(session_scope, "house_profile_longitude"),
        )
    with col_land:
        land = st.selectbox(
            "Land",
            options=["AT", "DE", "CH"],
            key=land_key,
            help="Land für Tariffilter im Szenarienkonfigurator (Bezug/Einspeise).",
        )
    timezone_name = "Europe/Vienna"
    try:
        from house_config.geo_timezone import lookup_timezone_name

        timezone_name = lookup_timezone_name(float(latitude), float(longitude))
        st.caption(f"Zeitzone (abgeleitet): **{timezone_name}**")
    except ValueError as exc:
        st.warning(str(exc))
    col_c, col_d = st.columns(2)
    with col_c:
        default_pv_tilt = labeled_number_input(
            "PV-Default Neigung (°)",
            min_value=0,
            max_value=90,
            help="Vorschlag für neue PV-Anlage im Tab PV-Anlagen (überschreibbar).",
            key=_scoped_key(session_scope, "house_profile_default_pv_tilt"),
        )
    with col_d:
        default_pv_azimuth = labeled_number_input(
            "PV-Default Azimut (°)",
            min_value=-180,
            max_value=180,
            help="0 = Süd, -90 = Ost, 90 = West. Überschreibbar im Tab PV-Anlagen.",
            key=_scoped_key(session_scope, "house_profile_default_pv_azimuth"),
        )
    nne_ap = labeled_number_input(
        "Netznutzung Arbeitspreis (Cent/kWh)",
        min_value=0.0,
        step=0.001,
        help=(
            "Volumetrischer Netznutzungs-Arbeitspreis netto (ohne USt), unabhängig vom "
            "Lieferantentarif. Wird zum Bezugspreis addiert (Live und SE). "
            "AT-Orientierung: docs/referenz/Netznutzungsentgelte-Austria-2026.csv"
        ),
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, "house_profile_nne_ap"),
    )
    return {
        "land": str(land),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "timezone_name": timezone_name,
        "default_pv_tilt": float(default_pv_tilt),
        "default_pv_azimuth": float(default_pv_azimuth),
        "netznutzung_arbeitspreis_cent_kwh": float(nne_ap or 0.0),
    }

def _render_thermal_rc_fields(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
) -> dict:
    rc = consumer.get("thermal_rc") if isinstance(consumer.get("thermal_rc"), dict) else consumer
    item: dict = {
        "min_on_quarterhours": labeled_number_input(
            "Mindestlaufzeit (Viertelstunden)",
            min_value=0,
            value=int(consumer.get("min_on_quarterhours", 8)),
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_rc_min_qh_{index}"),
        ),
        "thermal_rc": {
            "water_volume_liters": labeled_number_input(
                "Thermisches Volumen (Liter)",
                min_value=1.0,
                value=float(rc.get("water_volume_liters", 6000.0) or 6000.0),
                step=100.0,
                ratios=WIDE_LABEL_RATIOS,
                key=_scoped_key(session_scope, f"hc_rc_vol_{index}"),
            ),
            "setpoint_c": labeled_number_input(
                "Solltemperatur (°C)",
                value=float(rc.get("setpoint_c", 36.5)),
                step=0.5,
                key=_scoped_key(session_scope, f"hc_rc_set_{index}"),
            ),
            "tolerance_c": labeled_number_input(
                "Toleranz (± °C)",
                min_value=0.0,
                value=float(rc.get("tolerance_c", 1.0) or 1.0),
                step=0.1,
                key=_scoped_key(session_scope, f"hc_rc_tol_{index}"),
            ),
            "heat_loss_kw_per_k": labeled_number_input(
                "Wärmeverlust U (kW/K)",
                min_value=0.0,
                value=float(rc.get("heat_loss_kw_per_k", 0.1) or 0.1),
                format="%.4f",
                step=0.001,
                key=_scoped_key(session_scope, f"hc_rc_u_{index}"),
            ),
            "heating_efficiency": labeled_number_input(
                "Heizwirkungsgrad",
                min_value=0.01,
                max_value=1.0,
                value=float(rc.get("heating_efficiency", 0.95) or 0.95),
                step=0.01,
                key=_scoped_key(session_scope, f"hc_rc_eff_{index}"),
            ),
        },
    }
    if _live_markers_enabled():
        st.caption(
            "Thermal-/Filter-Merker unter **Daemon Control → EHAL-Com** "
            "(Entity-Mapping) pflegen."
        )
    return item

def _render_thermal_annual_building_fields(
    consumer: dict,
    thermal: dict,
    index: int,
    *,
    session_scope: str,
) -> dict:
    item: dict = {
        "min_on_quarterhours": labeled_number_input(
            "Mindestlaufzeit (Viertelstunden)",
            min_value=0,
            value=int(consumer.get("min_on_quarterhours", 4)),
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ta_min_qh_{index}"),
        ),
        "living_area_m2": labeled_number_input(
            "Wohnfläche (m²)",
            min_value=0.0,
            value=float(thermal.get("living_area_m2", 120.0)),
            key=_scoped_key(session_scope, f"hc_area_{index}"),
        ),
    }
    building_class = int(thermal.get("building_class", 3))
    item["building_class"] = labeled_selectbox(
        "Gebäudeklasse",
        options=[1, 2, 3, 4],
        index=max(0, min(3, building_class - 1)),
        format_func=building_class_option_label,
        key=_scoped_key(session_scope, f"hc_class_{index}"),
    )
    use_exact_hwb = labeled_checkbox(
        "Genaue HWB-Angabe",
        value=bool(float(thermal.get("hwb_kwh_m2", 0.0) or 0.0) > 0),
        key=_scoped_key(session_scope, f"hc_hwb_use_{index}"),
    )
    if use_exact_hwb:
        from data.heating_need import specific_heating_kwh_m2

        default_hwb = float(thermal.get("hwb_kwh_m2", 0.0) or 0.0)
        if default_hwb <= 0:
            default_hwb = specific_heating_kwh_m2(int(item["building_class"]))
        item["hwb_kwh_m2"] = labeled_number_input(
            "HWB (kWh/m²a)",
            min_value=0.1,
            value=default_hwb,
            step=1.0,
            key=_scoped_key(session_scope, f"hc_hwb_{index}"),
        )
    return item


def _render_thermal_annual_wp_preview(
    item: dict,
    thermal: dict,
    index: int,
    *,
    session_scope: str,
    location: dict,
) -> None:
    latitude = location["latitude"]
    longitude = location["longitude"]
    default_pv_tilt = location["default_pv_tilt"]
    default_pv_azimuth = location["default_pv_azimuth"]
    item["heat_pump_type"] = labeled_selectbox(
        "WP-Typ",
        options=["luft", "erde"],
        index=0 if thermal.get("heat_pump_type") != "erde" else 1,
        key=_scoped_key(session_scope, f"hc_wp_{index}"),
    )
    item["persons"] = labeled_number_input(
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
    if _live_markers_enabled():
        st.caption(
            "WP-Merker unter **Daemon Control → EHAL-Com** "
            "(Entity-Mapping, `flex.*`) pflegen."
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


def _render_thermal_annual_fields(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
    location: dict,
) -> dict:
    thermal = consumer.get("thermal") or consumer
    item = _render_thermal_annual_building_fields(
        consumer, thermal, index, session_scope=session_scope
    )
    _render_thermal_annual_wp_preview(
        item,
        thermal,
        index,
        session_scope=session_scope,
        location=location,
    )
    return item


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
        "solar_thermal_area_m2": labeled_number_input(
            "Solar-Kollektor Fläche (m²)",
            min_value=0.0,
            value=float(thermal.get("solar_thermal_area_m2", 0.0) or 0.0),
            step=1.0,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_solar_area_{index}"),
        ),
        "solar_thermal_tilt_deg": labeled_number_input(
            "Solar-Kollektor Neigung (°)",
            min_value=0,
            max_value=90,
            value=tilt_fallback,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_solar_tilt_{index}"),
        ),
        "solar_thermal_azimuth_deg": labeled_number_input(
            "Solar-Kollektor Azimut (°)",
            min_value=-180,
            max_value=180,
            value=azimuth_fallback,
            help="0 = Süd, -90 = Ost, 90 = West",
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_solar_azimuth_{index}"),
        ),
    }

def _live_consumer_for_annual(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
) -> dict:
    """Overlay live widget values onto consumer so expander kWh/a matches edits."""
    preview = dict(consumer)
    nom_key = _scoped_key(session_scope, f"hc_nom_{index}")
    if nom_key in st.session_state:
        preview["nominal_power_kw"] = float(st.session_state[nom_key])
    type_key = _scoped_key(session_scope, f"hc_type_{index}")
    if type_key in st.session_state:
        preview["type"] = st.session_state[type_key]
    c_type = str(preview.get("type", "generic"))
    if c_type == "generic":
        sched = dict(preview.get("schedule") or {})
        runs_key = _scoped_key(session_scope, f"hc_runs_{index}")
        dur_key = _scoped_key(session_scope, f"hc_duration_{index}")
        if runs_key in st.session_state:
            sched["runs_per_week"] = int(st.session_state[runs_key])
        if dur_key in st.session_state:
            sched["duration_h"] = float(st.session_state[dur_key])
        preview["schedule"] = sched
    elif c_type == "thermal_annual":
        for field, key_suffix, cast in (
            ("living_area_m2", f"hc_area_{index}", float),
            ("building_class", f"hc_class_{index}", int),
            ("persons", f"hc_persons_{index}", int),
            ("heat_pump_type", f"hc_wp_{index}", str),
            ("hwb_kwh_m2", f"hc_hwb_{index}", float),
        ):
            key = _scoped_key(session_scope, key_suffix)
            if key in st.session_state:
                preview[field] = cast(st.session_state[key])
    elif c_type == "ev":
        for field, key_suffix, cast in (
            ("battery_capacity_kwh", f"hc_ev_cap_{index}", float),
            ("min_power_kw", f"hc_ev_min_{index}", float),
        ):
            key = _scoped_key(session_scope, key_suffix)
            if key in st.session_state:
                preview[field] = cast(st.session_state[key])
        sched = dict(preview.get("charging_schedule") or {})
        for field, key_suffix, cast in (
            ("target_soc_percent", f"hc_ev_target_soc_{index}", float),
            ("charging_efficiency", f"hc_ev_eff_{index}", float),
        ):
            key = _scoped_key(session_scope, key_suffix)
            if key in st.session_state:
                sched[field] = cast(st.session_state[key])
        preview["charging_schedule"] = sched
    elif c_type == "thermal_rc":
        rc = dict(preview.get("thermal_rc") or {})
        for field, key_suffix, cast in (
            ("water_volume_liters", f"hc_rc_vol_{index}", float),
            ("setpoint_c", f"hc_rc_set_{index}", float),
            ("tolerance_c", f"hc_rc_tol_{index}", float),
            ("heat_loss_kw_per_k", f"hc_rc_u_{index}", float),
            ("heating_efficiency", f"hc_rc_eff_{index}", float),
        ):
            key = _scoped_key(session_scope, key_suffix)
            if key in st.session_state:
                rc[field] = cast(st.session_state[key])
        preview["thermal_rc"] = rc
    return preview

def _consumer_expander_title(
    consumer: dict, index: int, *, session_scope: str
) -> tuple[str, float, str]:
    """Prefer live Bezeichnung/params so expander header updates for every type.

    Returns ``(title, annual_kwh, type_key)`` — annual and type remount the expander
    when they change (stable keys alone can leave a stale label in the UI).
    """
    from house_config.baseload import consumer_annual_kwh

    label_key = _scoped_key(session_scope, f"hc_label_{index}")
    live = st.session_state.get(label_key)
    if live is None:
        live = consumer.get("label")
    title = str(live or "").strip() or f"Verbraucher {index + 1}"
    preview = _live_consumer_for_annual(consumer, index, session_scope=session_scope)
    c_type = str(preview.get("type", "generic") or "generic")
    type_label = CONSUMER_TYPE_LABELS.get(c_type, c_type)
    try:
        annual = float(consumer_annual_kwh(preview))
    except (TypeError, ValueError, OSError):
        annual = float(preview.get("annual_kwh", 0.0) or 0.0)
    return (
        f"Verbraucher {index + 1} ({type_label}): {title} — {annual:.0f} kWh/a",
        annual,
        c_type,
    )
