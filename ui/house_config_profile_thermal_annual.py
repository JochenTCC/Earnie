"""thermal_annual consumer fields of the house profile editor (split from house_config_profile_thermal)."""
from __future__ import annotations

from ui.house_config_profile_session import _live_markers_enabled, _scoped_key
import streamlit as st
from house_config.profile_schema_defaults import (
    consumer_default,
    heat_storage_default,
)
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
        normalize_building_mass,
    )

    mass_options = list(BUILDING_MASS_C_WH_PER_M2K.keys())
    mass_current = normalize_building_mass(thermal.get("building_mass"))
    return labeled_selectbox(
        "Bauweise (Wärmespeicher)",
        options=mass_options,
        index=mass_options.index(mass_current)
        if mass_current in mass_options
        else mass_options.index(consumer_default("building_mass")),
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
    st.markdown("**Gebäude / Wärmebedarf**")
    item: dict = {
        "living_area_m2": labeled_number_input(
            "Wohnfläche (m²)",
            min_value=0.0,
            value=float(
                thermal.get("living_area_m2", consumer_default("living_area_m2"))
            ),
            key=_scoped_key(session_scope, f"hc_area_{index}"),
        ),
    }
    building_class = int(
        thermal.get("building_class", consumer_default("building_class"))
    )
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


_HEAT_SOURCE_LABELS = {
    "heat_pump": "Wärmepumpe",
    "oil": "Öl",
    "gas": "Gas",
    "pellets": "Pellets",
    "district_heat": "Fernwärme",
    "wood": "Stückholz",
    "electric_direct": "Stromheizung (direkt)",
}
_HEAT_PUMP_LABELS = {"luft": "Luft", "erde": "Erde (Sole)", "grundwasser": "Grundwasser"}
_FUEL_UNIT_LABELS = {
    "ct_per_liter": "ct/l",
    "ct_per_kwh": "ct/kWh",
    "eur_per_ton": "€/t",
    "eur_per_rm": "€/rm",
}


def _heat_source_select_start(existing: dict) -> tuple[str, str]:
    """Start values ``(type, heat_pump_type)`` of the heat-source selectboxes.

    The expander preview uses the same values: on the switch to "Haus Wärme" it runs
    before the selectboxes exist and must compute with what the form is about to show.
    """
    from house_config.heat_source import HEAT_PUMP_TYPES, HEAT_SOURCE_TYPES

    source_type = str(existing.get("type") or "heat_pump")
    if source_type not in HEAT_SOURCE_TYPES:
        source_type = HEAT_SOURCE_TYPES[0]
    hp_type = str(existing.get("heat_pump_type") or "luft")
    if hp_type not in HEAT_PUMP_TYPES:
        hp_type = HEAT_PUMP_TYPES[0]
    return source_type, hp_type


def _render_heat_source_fields(thermal: dict, index: int, *, session_scope: str) -> dict:
    """Heat source (SUSI P1): type, heat-pump kind, optional efficiency / fuel price."""
    from house_config.heat_source import (
        HEAT_PUMP_TYPES,
        HEAT_SOURCE_TYPES,
        default_efficiency,
        fuel_price_in_unit,
        fuel_unit,
        heat_source_defaults,
        heat_source_is_electric,
    )

    existing = thermal.get("heat_source") if isinstance(thermal.get("heat_source"), dict) else {}
    start_type, start_hp = _heat_source_select_start(existing)
    source_type = labeled_selectbox(
        "Wärmequelle",
        options=list(HEAT_SOURCE_TYPES),
        index=list(HEAT_SOURCE_TYPES).index(start_type),
        format_func=lambda key: _HEAT_SOURCE_LABELS.get(key, key),
        key=_scoped_key(session_scope, f"hc_heat_source_{index}"),
    )
    heat_source: dict = {"type": source_type}
    if source_type == "heat_pump":
        heat_source["heat_pump_type"] = labeled_selectbox(
            "WP-Typ",
            options=list(HEAT_PUMP_TYPES),
            index=list(HEAT_PUMP_TYPES).index(start_hp),
            format_func=lambda key: _HEAT_PUMP_LABELS.get(key, key),
            key=_scoped_key(session_scope, f"hc_wp_{index}"),
        )
    same_type = existing.get("type") == source_type
    default_eff = default_efficiency(heat_source)
    eff_label = "JAZ" if source_type == "heat_pump" else "Nutzungsgrad"
    own_eff = labeled_checkbox(
        f"Eigene {eff_label} (Standard {default_eff:.2f})",
        value=same_type and existing.get("efficiency") not in (None, ""),
        key=_scoped_key(session_scope, f"hc_heat_eff_use_{index}"),
    )
    if own_eff:
        heat_source["efficiency"] = labeled_number_input(
            eff_label,
            min_value=0.05,
            value=float((existing.get("efficiency") if same_type else None) or default_eff),
            step=0.05,
            key=_scoped_key(session_scope, f"hc_heat_eff_{index}"),
        )
    if not heat_source_is_electric(heat_source):
        unit = _FUEL_UNIT_LABELS[str(fuel_unit(heat_source))]
        default_price = fuel_price_in_unit({"type": source_type})
        as_of = heat_source_defaults()["fuel_price_as_of"]
        own_price = labeled_checkbox(
            f"Eigener Brennstoffpreis (Standard {default_price:g} {unit}, Stand {as_of})",
            value=same_type and existing.get("fuel_price") not in (None, ""),
            key=_scoped_key(session_scope, f"hc_fuel_price_use_{index}"),
        )
        if own_price:
            heat_source["fuel_price"] = labeled_number_input(
                f"Brennstoffpreis ({unit})",
                min_value=0.01,
                value=float((existing.get("fuel_price") if same_type else None) or default_price),
                step=0.5,
                key=_scoped_key(session_scope, f"hc_fuel_price_{index}"),
            )
    return heat_source


def _render_heating_rod_fields(
    consumer: dict, index: int, *, session_scope: str
) -> list[dict]:
    """Heating rod part (only with heat storage); η = 1 into the store, planned by the MILP."""
    from house_config.heat_source import (
        HEATING_ROD_PART_ID,
        HEATING_ROD_PART_TYPE,
        heating_rod_part,
    )

    existing = heating_rod_part(consumer)
    enabled = labeled_checkbox(
        "Heizstab im Wärmespeicher",
        value=existing is not None,
        key=_scoped_key(session_scope, f"hc_rod_use_{index}"),
    )
    if not enabled:
        return []
    power = labeled_number_input(
        "Heizstab Leistung (kW)",
        min_value=0.1,
        value=float((existing or {}).get("nominal_power_kw") or 3.0),
        step=0.5,
        help=(
            "Lädt den Wärmespeicher mit Wirkungsgrad 1. Der Optimierer setzt ihn ein, "
            "wenn Strom günstiger ist als Wärme aus der Hauptquelle (Planung im "
            "Szenarien-Explorer; Live-Steuerung folgt mit eigenem EHAL-Binding)."
        ),
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, f"hc_rod_kw_{index}"),
    )
    return [
        {
            "id": HEATING_ROD_PART_ID,
            "type": HEATING_ROD_PART_TYPE,
            "nominal_power_kw": float(power),
        }
    ]


_MEASURED_ROD_NONE = "Keine Angabe"
_MEASURED_ROD_ANNUAL = "Jahresverbrauch (kWh)"
_MEASURED_ROD_CSV = "Eigene CSV-Datei"


def _render_measured_rod_fields(
    consumer: dict, index: int, *, session_scope: str
) -> dict:
    """Measured consumption of the real heating rod (SE baseload only, no EHAL binding)."""
    from house_config.heating_systems import ROD_ANNUAL_KWH_KEY, ROD_PROFILE_CSV_KEY

    if consumer.get(ROD_PROFILE_CSV_KEY):
        start = _MEASURED_ROD_CSV
    elif consumer.get(ROD_ANNUAL_KWH_KEY) is not None:
        start = _MEASURED_ROD_ANNUAL
    else:
        start = _MEASURED_ROD_NONE
    options = [_MEASURED_ROD_NONE, _MEASURED_ROD_ANNUAL, _MEASURED_ROD_CSV]
    mode = labeled_selectbox(
        "Gemessener Heizstab-Verbrauch",
        options=options,
        index=options.index(start),
        help=(
            "Nur für den Szenario-Explorer mit Messdaten: Lief der Heizstab im Messzeitraum, "
            "steckt sein Verbrauch im Gesamtverbrauch. Mit CSV oder Jahres-kWh zieht Earnie "
            "ihn von der Grundlast ab, sonst kann er doppelt gezählt werden."
        ),
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, f"hc_rod_measured_mode_{index}"),
    )
    if mode == _MEASURED_ROD_ANNUAL:
        kwh = labeled_number_input(
            "Heizstab Jahresverbrauch (kWh)",
            min_value=1.0,
            value=float(consumer.get(ROD_ANNUAL_KWH_KEY) or 100.0),
            step=50.0,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_rod_measured_kwh_{index}"),
        )
        return {ROD_ANNUAL_KWH_KEY: float(kwh)}
    if mode == _MEASURED_ROD_CSV:
        from ui.form_layout import labeled_text_input

        path = labeled_text_input(
            "Heizstab CSV (Pfad)",
            value=str(consumer.get(ROD_PROFILE_CSV_KEY) or ""),
            help="Stundenwerte in kW, gleiches Format wie die Verbrauchs-CSV der Verbraucher.",
            key=_scoped_key(session_scope, f"hc_rod_measured_csv_{index}"),
        )
        return {ROD_PROFILE_CSV_KEY: str(path).strip()} if str(path).strip() else {}
    return {}


def _render_thermal_comfort_fields(
    item: dict,
    thermal: dict,
    index: int,
    *,
    session_scope: str,
) -> None:
    item["persons"] = labeled_number_input(
        "Personen",
        min_value=1,
        value=int(thermal.get("persons", consumer_default("persons"))),
        key=_scoped_key(session_scope, f"hc_persons_{index}"),
    )
    item["target_temp_c"] = labeled_number_input(
        "Solltemperatur (°C)",
        value=float(
            thermal.get("target_temp_c", consumer_default("target_temp_c"))
        ),
        step=0.5,
        key=_scoped_key(session_scope, f"hc_target_temp_{index}"),
    )
    item["house_tolerance_c"] = labeled_number_input(
        "Heizband Toleranz (K)",
        min_value=0.05,
        value=float(
            thermal.get("house_tolerance_c", consumer_default("house_tolerance_c"))
        ),
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
        value=float(
            thermal.get(
                "absent_temp_reduction_c", consumer_default("absent_temp_reduction_c")
            )
        ),
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
    from data.modeled_climate import thermal_annual_fuel_kwh_from_archive
    from house_config.heat_source import heat_source_is_electric

    thermal_preview = {**item, "latitude": latitude, "longitude": longitude}
    house_profile = {
        "latitude": latitude,
        "longitude": longitude,
        "default_pv_tilt": location["default_pv_tilt"],
        "default_pv_azimuth": location["default_pv_azimuth"],
    }
    if heat_source_is_electric(item["heat_source"]):
        wp_annual, ref_year = thermal_annual_kwh_from_archive(
            thermal_preview, house_profile=house_profile
        )
        st.metric("Geschätzter Strombedarf Heizung (kWh/a)", f"{wp_annual:.0f}")
    else:
        fuel_annual, ref_year = thermal_annual_fuel_kwh_from_archive(
            thermal_preview, house_profile=house_profile
        )
        st.metric("Geschätzter Brennstoffbedarf (kWh/a Endenergie)", f"{fuel_annual:.0f}")
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
        value=float(
            existing.get("volume_liters") or heat_storage_default("volume_liters")
        ),
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
            value=float(
                existing.get("heat_loss_kw_per_k")
                or heat_storage_default("heat_loss_kw_per_k")
            ),
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
            value=float(
                existing.get("setpoint_c", heat_storage_default("setpoint_c"))
            ),
            step=1.0,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_storage_set_{index}"),
        ),
        "tolerance_c": labeled_number_input(
            "Wärmespeicher Toleranz (K)",
            min_value=0.1,
            value=float(
                existing.get("tolerance_c") or heat_storage_default("tolerance_c")
            ),
            step=0.5,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_storage_tol_{index}"),
        ),
    }


def _reference_system_heading(consumer: dict, *, session_scope: str) -> str:
    """Section heading of the generation fields; names the referenced catalog entry.

    The form consumer carries the generation fields inline, not ``heating_system_id``; the
    reference comes from the saved house file, as on save (``merge_inline_heating_systems``).
    ``session_scope`` is the profile id (``__new__`` for an unsaved profile).
    """
    from house_config.heating_systems import (
        HEATING_SYSTEM_ID_KEY,
        load_heating_systems_for_house,
        read_raw_json,
        reference_ids_by_profile,
    )
    from runtime_store.persist_paths import resolve_house_profiles_json_path

    house_path = resolve_house_profiles_json_path()
    system_id = str(consumer.get(HEATING_SYSTEM_ID_KEY) or "").strip()
    if not system_id:
        refs = reference_ids_by_profile(read_raw_json(house_path)).get(session_scope, {})
        system_id = refs.get(str(consumer.get("id") or ""), "")
    entry = load_heating_systems_for_house(house_path).get(system_id) if system_id else None
    if entry is None:
        return "**Heizsystem (Referenzsystem, wird beim Speichern angelegt)**"
    return f"**Heizsystem (Referenzsystem: {entry['label']})**"


def _render_reference_system_fields(
    item: dict,
    consumer: dict,
    thermal: dict,
    index: int,
    *,
    session_scope: str,
) -> None:
    """Generation fields; saving moves them into the referenced ``heating_systems[]`` entry."""
    st.markdown(_reference_system_heading(consumer, session_scope=session_scope))
    st.caption(
        "Die eingebaute Heizung. Weitere Heizsysteme für den Vergleich im Szenario-Explorer "
        "im Bereich „Heizsysteme“ oben anlegen."
    )
    item["heat_source"] = _render_heat_source_fields(
        thermal, index, session_scope=session_scope
    )
    item["nominal_power_kw"] = float(
        labeled_number_input(
            "Nennleistung Wärmepumpe (kW, elektrisch)",
            min_value=0.0,
            value=float(consumer.get("nominal_power_kw", 0.0)),
            key=_scoped_key(session_scope, f"hc_nom_{index}"),
        )
    )
    item["min_on_quarterhours"] = labeled_number_input(
        "Mindestlaufzeit (Viertelstunden)",
        min_value=1,
        value=int(
            consumer.get(
                "min_on_quarterhours",
                consumer_default("min_on_quarterhours", consumer_type="thermal_annual"),
            )
        ),
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, f"hc_ta_min_qh_{index}"),
    )
    storage = _render_thermal_storage_fields(
        thermal, index, session_scope=session_scope
    )
    if storage is not None:
        item["heat_storage"] = storage
        parts = _render_heating_rod_fields(consumer, index, session_scope=session_scope)
        if parts:
            item["parts"] = parts
            item.update(
                _render_measured_rod_fields(consumer, index, session_scope=session_scope)
            )


def _render_thermal_annual_wp_preview(
    item: dict,
    consumer: dict,
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
    _render_reference_system_fields(
        item, consumer, thermal, index, session_scope=session_scope
    )
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
        consumer,
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
    default_tilt: float | None = None,
    default_azimuth: float | None = None,
) -> dict:
    if default_tilt is None:
        default_tilt = consumer_default("solar_thermal_tilt_deg")
    if default_azimuth is None:
        default_azimuth = consumer_default("solar_thermal_azimuth_deg")
    tilt_fallback = int(thermal.get("solar_thermal_tilt_deg", default_tilt))
    azimuth_fallback = int(thermal.get("solar_thermal_azimuth_deg", default_azimuth))
    return {
        "solar_thermal_area_m2": labeled_number_input(
            "Solar-Kollektor Fläche (m²)",
            min_value=0.0,
            value=float(
                thermal.get("solar_thermal_area_m2")
                or consumer_default("solar_thermal_area_m2")
            ),
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
            ("hwb_kwh_m2", f"hc_hwb_{index}", float),
            ("house_tolerance_c", f"hc_house_tol_{index}", float),
            ("house_heat_loss_kw_per_k", f"hc_house_h_{index}", float),
        ),
    )
    stored = preview.get("heat_source") if isinstance(preview.get("heat_source"), dict) else {}
    start_type, start_hp = _heat_source_select_start(stored)
    heat_source = {**stored, "type": start_type, "heat_pump_type": start_hp}
    _overlay_session_fields(
        heat_source,
        session_scope,
        (
            ("type", f"hc_heat_source_{index}", str),
            ("heat_pump_type", f"hc_wp_{index}", str),
        ),
    )
    if heat_source.get("type") != stored.get("type"):
        heat_source.pop("efficiency", None)
        heat_source.pop("fuel_price", None)
    if heat_source.get("type") != "heat_pump":
        heat_source.pop("heat_pump_type", None)
    preview["heat_source"] = heat_source
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
