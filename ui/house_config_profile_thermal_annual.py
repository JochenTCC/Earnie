"""thermal_annual consumer fields of the house profile editor (split from house_config_profile_thermal)."""
from __future__ import annotations

from ui.house_config_profile_session import _live_markers_enabled, _scoped_key
import streamlit as st
from house_config.thermal_labels import (
    building_class_option_label,
)
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
    labeled_checkbox,
    labeled_number_input,
    labeled_selectbox,
)


def _render_building_mass_select(
    thermal: dict, index: int, *, session_scope: str
) -> str:
    from optimizer.thermal_house import (
        BUILDING_MASS_C_WH_PER_M2K,
        DEFAULT_BUILDING_MASS,
        normalize_building_mass,
    )

    mass_options = list(BUILDING_MASS_C_WH_PER_M2K.keys())
    mass_current = normalize_building_mass(thermal.get("building_mass"))
    return labeled_selectbox(
        "Bauweise (Wärmespeicher)",
        options=mass_options,
        index=mass_options.index(mass_current)
        if mass_current in mass_options
        else mass_options.index(DEFAULT_BUILDING_MASS),
        format_func=lambda key: {
            "leicht": "Leicht (50 Wh/m²K)",
            "mittel": "Mittel (90 Wh/m²K)",
            "schwer": "Schwer (130 Wh/m²K)",
        }.get(key, key),
        key=_scoped_key(session_scope, f"hc_building_mass_{index}"),
    )


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
    item["building_mass"] = _render_building_mass_select(
        thermal, index, session_scope=session_scope
    )
    st.caption(
        "DIN V 18599-2: wirksame Wärmekapazität C = Wert × Wohnfläche "
        "(für Aufheizen/Auskühlen in Übergangszeiten)."
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


def _render_thermal_comfort_fields(
    item: dict,
    thermal: dict,
    index: int,
    *,
    session_scope: str,
) -> None:
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
    item["target_temp_c"] = labeled_number_input(
        "Solltemperatur (°C)",
        value=float(thermal.get("target_temp_c", 21.5)),
        step=0.5,
        key=_scoped_key(session_scope, f"hc_target_temp_{index}"),
    )
    from optimizer.thermal_house import DEFAULT_HOUSE_TOLERANCE_C

    item["house_tolerance_c"] = labeled_number_input(
        "Heizband Toleranz (K)",
        min_value=0.05,
        value=float(thermal.get("house_tolerance_c", DEFAULT_HOUSE_TOLERANCE_C)),
        step=0.1,
        key=_scoped_key(session_scope, f"hc_house_tol_{index}"),
    )
    h_existing = thermal.get("house_heat_loss_kw_per_k")
    h_value = float(h_existing) if h_existing not in (None, "") else 0.0
    item_h = labeled_number_input(
        "Haus-Verlustkoeffizient H (kW/K, 0 = auto aus HWB)",
        min_value=0.0,
        value=h_value,
        step=0.01,
        format="%.3f",
        key=_scoped_key(session_scope, f"hc_house_h_{index}"),
    )
    if float(item_h) > 0.0:
        item["house_heat_loss_kw_per_k"] = float(item_h)
    item["absent_temp_reduction_c"] = labeled_number_input(
        "Temperaturabsenkung wenn abwesend",
        min_value=0.0,
        value=float(thermal.get("absent_temp_reduction_c", 6.5)),
        step=0.5,
        key=_scoped_key(session_scope, f"hc_absent_temp_red_{index}"),
        help=(
            "Bei wirksamem Abwesenheitsmodus und aktiver Verbraucher-Option: "
            "Live-Soll = Solltemperatur − Absenkung; Warmwasser dann 0."
        ),
    )


def _render_wp_annual_metric(item: dict, *, location: dict) -> None:
    from data.modeled_climate import thermal_annual_kwh_from_archive

    latitude = location["latitude"]
    longitude = location["longitude"]
    thermal_preview = {**item, "latitude": latitude, "longitude": longitude}
    wp_annual, ref_year = thermal_annual_kwh_from_archive(
        thermal_preview,
        house_profile={
            "latitude": latitude,
            "longitude": longitude,
            "default_pv_tilt": location["default_pv_tilt"],
            "default_pv_azimuth": location["default_pv_azimuth"],
        },
    )
    st.metric("Geschätzter WP-Jahresbedarf (kWh/a)", f"{wp_annual:.0f}")
    st.caption(
        f"Basis: Open-Meteo-Archiv {ref_year} "
        f"({latitude:.4f}°N, {longitude:.4f}°E)"
    )


def _render_thermal_storage_fields(
    thermal: dict,
    index: int,
    *,
    session_scope: str,
) -> dict | None:
    """Optional heat storage; volume 0 disables coupled path (legacy open-loop)."""
    existing = thermal.get("heat_storage") if isinstance(thermal.get("heat_storage"), dict) else {}
    volume = labeled_number_input(
        "Wärmespeicher Volumen (Liter)",
        min_value=0.0,
        value=float(existing.get("volume_liters", 0.0) or 0.0),
        step=50.0,
        help=(
            "0 = bisheriges Modell (Solar als Tages-Gutschrift). "
            ">0 = gekoppelt: Solar und WP speisen den Speicher, Hausbedarf entnimmt."
        ),
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, f"hc_storage_vol_{index}"),
    )
    if float(volume) <= 0.0:
        return None
    return {
        "volume_liters": float(volume),
        "heat_loss_kw_per_k": labeled_number_input(
            "Wärmespeicher Verlust (kW/K)",
            min_value=0.0,
            value=float(existing.get("heat_loss_kw_per_k", 0.02) or 0.02),
            step=0.005,
            format="%.3f",
            help=(
                "U des Speichers gegen Umgebung (typ. ~0.005–0.02), "
                "nicht Gebäude-LT+LV aus dem Energieausweis. "
                "Zu groß → Sommer-WP-Bedarf trotz Solar zu hoch."
            ),
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_storage_u_{index}"),
        ),
        "setpoint_c": labeled_number_input(
            "Wärmespeicher Soll (°C)",
            value=float(existing.get("setpoint_c", 45.0)),
            step=1.0,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_storage_set_{index}"),
        ),
        "tolerance_c": labeled_number_input(
            "Wärmespeicher Toleranz (K)",
            min_value=0.1,
            value=float(existing.get("tolerance_c", 5.0) or 5.0),
            step=0.5,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_storage_tol_{index}"),
        ),
    }


def _render_thermal_annual_wp_preview(
    item: dict,
    thermal: dict,
    index: int,
    *,
    session_scope: str,
    location: dict,
) -> None:
    _render_thermal_comfort_fields(
        item, thermal, index, session_scope=session_scope
    )
    item.update(
        _render_thermal_solar_fields(
            thermal,
            index,
            session_scope=session_scope,
            default_tilt=location["default_pv_tilt"],
            default_azimuth=location["default_pv_azimuth"],
        )
    )
    storage = _render_thermal_storage_fields(
        thermal, index, session_scope=session_scope
    )
    if storage is not None:
        item["heat_storage"] = storage
    if _live_markers_enabled():
        st.caption(
            "WP-Bindings unter **Daemon Control → EHAL-Com** "
            "(Entity-Mapping, `flex.*`) pflegen."
        )
    _render_wp_annual_metric(item, location=location)


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


def _profile_geo_from_session(session_scope: str) -> tuple[float | None, float | None, str | None]:
    """Live Standort widgets — form edit drops lat/lon from thermal_rc until save."""
    lat_key = _scoped_key(session_scope, "house_profile_latitude")
    lon_key = _scoped_key(session_scope, "house_profile_longitude")
    land_key = _scoped_key(session_scope, "house_profile_land")
    lat = float(st.session_state[lat_key]) if lat_key in st.session_state else None
    lon = float(st.session_state[lon_key]) if lon_key in st.session_state else None
    timezone_name = None
    if land_key in st.session_state:
        from house_config.geo_timezone import timezone_for_land

        timezone_name = timezone_for_land(str(st.session_state[land_key]))
    return lat, lon, timezone_name


def _overlay_session_fields(target: dict, session_scope: str, fields) -> None:
    """Copy live widget values (``(field, key_suffix, cast)``) into ``target``."""
    for field, key_suffix, cast in fields:
        key = _scoped_key(session_scope, key_suffix)
        if key in st.session_state:
            target[field] = cast(st.session_state[key])


def _overlay_profile_geo(target: dict, session_scope: str) -> None:
    lat, lon, timezone_name = _profile_geo_from_session(session_scope)
    if lat is not None:
        target["latitude"] = lat
    if lon is not None:
        target["longitude"] = lon
    if timezone_name:
        target["timezone_name"] = timezone_name


def _overlay_generic_schedule(preview: dict, index: int, session_scope: str) -> None:
    sched = dict(preview.get("schedule") or {})
    _overlay_session_fields(
        sched,
        session_scope,
        (
            ("runs_per_week", f"hc_runs_{index}", int),
            ("duration_h", f"hc_duration_{index}", float),
        ),
    )
    preview["schedule"] = sched


def _overlay_ev_fields(preview: dict, index: int, session_scope: str) -> None:
    _overlay_session_fields(
        preview,
        session_scope,
        (
            ("battery_capacity_kwh", f"hc_ev_cap_{index}", float),
            ("min_power_kw", f"hc_ev_min_{index}", float),
        ),
    )
    sched = dict(preview.get("charging_schedule") or {})
    _overlay_session_fields(
        sched,
        session_scope,
        (
            ("target_soc_percent", f"hc_ev_target_soc_{index}", float),
            ("charging_efficiency", f"hc_ev_eff_{index}", float),
        ),
    )
    preview["charging_schedule"] = sched


def _overlay_thermal_rc_fields(preview: dict, index: int, session_scope: str) -> None:
    rc = dict(preview.get("thermal_rc") or {})
    _overlay_session_fields(
        rc,
        session_scope,
        (
            ("water_volume_liters", f"hc_rc_vol_{index}", float),
            ("setpoint_c", f"hc_rc_set_{index}", float),
            ("tolerance_c", f"hc_rc_tol_{index}", float),
            ("heat_loss_kw_per_k", f"hc_rc_u_{index}", float),
            ("heating_efficiency", f"hc_rc_eff_{index}", float),
        ),
    )
    _overlay_profile_geo(rc, session_scope)
    preview["thermal_rc"] = rc


def _overlay_thermal_annual_fields(
    preview: dict, index: int, session_scope: str
) -> None:
    _overlay_session_fields(
        preview,
        session_scope,
        (
            ("living_area_m2", f"hc_area_{index}", float),
            ("building_class", f"hc_class_{index}", int),
            ("building_mass", f"hc_building_mass_{index}", str),
            ("persons", f"hc_persons_{index}", int),
            ("heat_pump_type", f"hc_wp_{index}", str),
            ("hwb_kwh_m2", f"hc_hwb_{index}", float),
            ("house_tolerance_c", f"hc_house_tol_{index}", float),
            ("house_heat_loss_kw_per_k", f"hc_house_h_{index}", float),
        ),
    )
    _overlay_profile_geo(preview, session_scope)


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
        _overlay_generic_schedule(preview, index, session_scope)
    elif c_type == "thermal_annual":
        _overlay_thermal_annual_fields(preview, index, session_scope)
    elif c_type == "ev":
        _overlay_ev_fields(preview, index, session_scope)
    elif c_type == "thermal_rc":
        _overlay_thermal_rc_fields(preview, index, session_scope)
    return preview
