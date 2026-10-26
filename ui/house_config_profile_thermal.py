"""Location / thermal consumer fields for Hausprofil form."""
from __future__ import annotations

from ui.house_config_profile_session import (
    _live_markers_enabled,
    _scoped_key,
    region_widget_key,
)


import streamlit as st

from house_config.thermal_labels import (
    CONSUMER_TYPE_LABELS,
)
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
    labeled_checkbox,
    labeled_number_input,
    labeled_selectbox,
)
from ui.house_config_profile_thermal_annual import (  # noqa: F401  (re-exported)
    _live_consumer_for_annual,
    _profile_geo_from_session,
    _render_thermal_annual_building_fields,
    _render_thermal_annual_fields,
    _render_thermal_annual_wp_preview,
    _render_thermal_comfort_fields,
    _render_thermal_solar_fields,
    _render_thermal_storage_fields,
    _render_wp_annual_metric,
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

def _seed_land_widget_key(session_scope: str) -> str:
    land_key = _scoped_key(session_scope, "house_profile_land")
    if land_key not in st.session_state:
        st.session_state[land_key] = "AT"
    elif st.session_state[land_key] not in {"AT", "DE", "CH"}:
        st.session_state[land_key] = "AT"
    return land_key

def _render_region_select(*, session_scope: str, land: str) -> str:
    from house_config.edibert_tariffs import holiday_regions, region_label

    options = ["", *holiday_regions(land)]
    key = region_widget_key(session_scope, land)
    if st.session_state.get(key) not in options:
        st.session_state[key] = ""
    region = st.selectbox(
        "Region (Feiertage)",
        options=options,
        key=key,
        format_func=lambda code: region_label(land, code),
        help=(
            "Bundesland bzw. Kanton für den Feiertagskalender. Nur nötig für Tarife "
            "mit Zeitregeln nach Wochentag/Feiertag (Benutzertarife aus Edibert)."
        ),
    )
    return str(region or "")


def _render_geo_row(*, session_scope: str, land_key: str) -> tuple[float, float, str]:
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
    return float(latitude), float(longitude), str(land)

def _render_pv_default_row(*, session_scope: str) -> tuple[float, float]:
    col_c, col_d = st.columns(2)
    with col_c:
        default_pv_tilt = labeled_number_input(
            "PV-Default Neigung (°)",
            min_value=0,
            max_value=90,
            help="Vorschlag für ein neues PV-Feld im Tab PV-Felder (überschreibbar).",
            key=_scoped_key(session_scope, "house_profile_default_pv_tilt"),
        )
    with col_d:
        default_pv_azimuth = labeled_number_input(
            "PV-Default Azimut (°)",
            min_value=-180,
            max_value=180,
            help="0 = Süd, -90 = Ost, 90 = West. Überschreibbar im Tab PV-Felder.",
            key=_scoped_key(session_scope, "house_profile_default_pv_azimuth"),
        )
    return float(default_pv_tilt), float(default_pv_azimuth)

NNE_AREA_MANUAL = "__manual__"


def _load_grid_fee_catalog_for_ui() -> dict:
    from data.grid_fees import load_grid_fee_catalog
    from runtime_store.persist_paths import resolve_grid_fees_json_path

    return load_grid_fee_catalog(resolve_grid_fees_json_path())


def _render_nne_area_fields(
    catalog: dict, *, session_scope: str
) -> tuple[str, float]:
    """Netzbereich select plus manual Arbeitspreis when no catalog area is chosen."""
    areas = catalog["areas"]
    area_key = _scoped_key(session_scope, "house_profile_nne_area")
    options = [NNE_AREA_MANUAL, *areas.keys()]
    area_choice = labeled_selectbox(
        "Netzbereich (Netznutzung)",
        options=options,
        format_func=lambda key: (
            "Eigener Wert (manuell)" if key == NNE_AREA_MANUAL else areas[key]["label"]
        ),
        help=(
            "Katalog Netznutzungs-Arbeitspreis (Netzebene 7) inkl. Zeitregeln wie "
            "SNAP/WiNAP. Netto (ohne USt), unabhängig vom Lieferantentarif."
        ),
        ratios=WIDE_LABEL_RATIOS,
        key=area_key,
    )
    base_manual = 0.0
    if area_choice == NNE_AREA_MANUAL:
        base_manual = float(
            labeled_number_input(
                "Netznutzung Arbeitspreis (Cent/kWh)",
                min_value=0.0,
                step=0.001,
                help="Konstanter Netznutzungs-Arbeitspreis netto (ohne USt), ohne Zeitregeln.",
                ratios=WIDE_LABEL_RATIOS,
                key=_scoped_key(session_scope, "house_profile_nne_ap"),
            )
            or 0.0
        )
    return area_choice, base_manual


def _show_nne_spec_caption(config: dict, catalog: dict) -> None:
    """Resolved base price and active time rules of the chosen Netzbereich."""
    from data.grid_fees import resolve_grid_fee_spec

    try:
        spec = resolve_grid_fee_spec(config, catalog, timezone_name="Europe/Vienna")
    except ValueError as exc:
        st.error(str(exc))
        return
    active = ", ".join(rule["id"] for rule in spec["rules"]) or "keine"
    skipped = ", ".join(
        f"{item['id']} ({item['reason']})" for item in spec["skipped"]
    )
    st.caption(
        f"Basis-Arbeitspreis: **{spec['base_cent_kwh']:.2f} Cent/kWh** netto · "
        f"aktive Zeitregeln: **{active}**"
        + (f" · übersprungen: {skipped}" if skipped else "")
    )


def _render_nne_arbeitspreis(*, session_scope: str) -> dict:
    """Netznutzung: Netzbereich aus Katalog oder eigener Wert; Zeitregeln."""
    from data.grid_fees import METERING_UNMETERED

    catalog = _load_grid_fee_catalog_for_ui()
    area_choice, base_manual = _render_nne_area_fields(
        catalog, session_scope=session_scope
    )
    include_draft = bool(
        labeled_checkbox(
            "Entwurfs-Regeln einbeziehen (noch nicht verordnet, z. B. WiNAP)",
            key=_scoped_key(session_scope, "house_profile_nne_include_draft"),
        )
    )
    config = {
        "area_id": None if area_choice == NNE_AREA_MANUAL else area_choice,
        "power_metering": METERING_UNMETERED,
        "quarter_hour_meter": True,
        "base_cent_kwh": base_manual,
        "include_status": ["verordnet", "entwurf"] if include_draft else ["verordnet"],
    }
    if config["area_id"] is not None:
        _show_nne_spec_caption(config, catalog)
    return config


def _render_location_fields(*, session_scope: str) -> dict:
    st.subheader("Standort")
    land_key = _seed_land_widget_key(session_scope)
    latitude, longitude, land = _render_geo_row(
        session_scope=session_scope, land_key=land_key
    )
    from house_config.geo_timezone import timezone_for_land

    timezone_name = timezone_for_land(land)
    st.caption(f"Zeitzone (aus Land): **{timezone_name}**")
    region = _render_region_select(session_scope=session_scope, land=land)
    default_pv_tilt, default_pv_azimuth = _render_pv_default_row(
        session_scope=session_scope
    )
    netznutzung = _render_nne_arbeitspreis(session_scope=session_scope)
    return {
        "land": land,
        "region": region,
        "latitude": latitude,
        "longitude": longitude,
        "timezone_name": timezone_name,
        "default_pv_tilt": default_pv_tilt,
        "default_pv_azimuth": default_pv_azimuth,
        "netznutzung": netznutzung,
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
            min_value=1,
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
            "Thermal-/Filter-Bindings unter **Daemon Control → EHAL-Com** "
            "(Entity-Mapping) pflegen."
        )
    return item

















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
