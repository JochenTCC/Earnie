"""EV consumer fields for Hausprofil form."""
from __future__ import annotations

from ui.house_config_profile_session import _live_markers_enabled, _scoped_key
from ui.house_config_profile_generic import _schedule_defaults

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

def _seed_ev_defaults_on_type_switch(
    consumer: dict, index: int, *, session_scope: str
) -> dict:
    """On Typ → EV, seed widget keys with EV defaults (keep label/id)."""
    type_key = _scoped_key(session_scope, f"hc_type_{index}")
    selected = st.session_state.get(type_key, consumer.get("type", "generic"))
    if str(selected) != "ev" or str(consumer.get("type", "generic")) == "ev":
        return consumer

    defaults = _default_ev_consumer()
    seeded = dict(defaults)
    if consumer.get("label"):
        seeded["label"] = consumer["label"]
    if consumer.get("id"):
        seeded["id"] = consumer["id"]
    _apply_ev_default_widget_keys(seeded, index, session_scope=session_scope)
    return seeded

def _apply_ev_default_widget_keys(
    seeded: dict, index: int, *, session_scope: str
) -> None:
    sched = seeded.get("charging_schedule") or {}
    weekday = sched.get("weekday") or {}
    weekend = sched.get("weekend") or {}
    values = {
        f"hc_nom_{index}": float(seeded["nominal_power_kw"]),
        f"hc_ev_min_{index}": float(seeded["min_power_kw"]),
        f"hc_ev_min_qh_{index}": int(seeded["min_on_quarterhours"]),
        f"hc_ev_cap_{index}": float(seeded["battery_capacity_kwh"]),
        f"hc_ev_target_soc_{index}": float(sched.get("target_soc_percent", 100.0)),
        f"hc_ev_eff_{index}": float(sched.get("charging_efficiency", 0.95)),
        f"hc_ev_forecast_{index}": bool(sched.get("forecast_when_absent", True)),
        f"hc_ev_Werktag_from_{index}": int(weekday.get("car_available_from_hour", 18)),
        f"hc_ev_Werktag_ready_{index}": int(weekday.get("ready_by_hour", 7)),
        f"hc_ev_Werktag_soc_{index}": float(weekday.get("daily_rest_soc", 40.0)),
        f"hc_ev_Wochenende_from_{index}": int(weekend.get("car_available_from_hour", 20)),
        f"hc_ev_Wochenende_ready_{index}": int(weekend.get("ready_by_hour", 9)),
        f"hc_ev_Wochenende_soc_{index}": float(weekend.get("daily_rest_soc", 30.0)),
    }
    for suffix, value in values.items():
        st.session_state[_scoped_key(session_scope, suffix)] = value

def _render_day_schedule(
    prefix: str,
    block: dict,
    *,
    index: int,
    session_scope: str,
) -> dict:
    return {
        "car_available_from_hour": labeled_number_input(
            f"{prefix}: Ankunft ab (Stunde)",
            min_value=0,
            max_value=23,
            value=int(block.get("car_available_from_hour", 18)),
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_{prefix}_from_{index}"),
        ),
        "ready_by_hour": labeled_number_input(
            f"{prefix}: Fertig bis (Stunde)",
            min_value=0,
            max_value=23,
            value=int(block.get("ready_by_hour", 7)),
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_{prefix}_ready_{index}"),
        ),
        "daily_rest_soc": labeled_number_input(
            f"{prefix}: Rest-SOC (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(block.get("daily_rest_soc", 30.0)),
            step=1.0,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_{prefix}_soc_{index}"),
        ),
    }

def _render_ev_fields(consumer: dict, index: int, *, session_scope: str) -> dict:
    sched = dict(consumer.get("charging_schedule") or {})
    item: dict = {
        "min_power_kw": labeled_number_input(
            "Mindestleistung (kW)",
            min_value=0.0,
            value=float(consumer.get("min_power_kw", 1.4)),
            key=_scoped_key(session_scope, f"hc_ev_min_{index}"),
        ),
        "min_on_quarterhours": labeled_number_input(
            "Mindest-Ladedauer (Viertelstunden)",
            min_value=0,
            value=int(consumer.get("min_on_quarterhours", 4)),
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_min_qh_{index}"),
        ),
        "battery_capacity_kwh": labeled_number_input(
            "Akkukapazität (kWh)",
            min_value=0.1,
            value=float(consumer.get("battery_capacity_kwh", 60.0)),
            step=1.0,
            key=_scoped_key(session_scope, f"hc_ev_cap_{index}"),
        ),
    }
    item["charging_schedule"] = {
        "target_soc_percent": labeled_number_input(
            "Ziel-SOC (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(sched.get("target_soc_percent", 100.0)),
            key=_scoped_key(session_scope, f"hc_ev_target_soc_{index}"),
        ),
        "charging_efficiency": labeled_number_input(
            "Lade-Wirkungsgrad",
            min_value=0.01,
            max_value=1.0,
            value=float(sched.get("charging_efficiency", 0.95)),
            step=0.01,
            key=_scoped_key(session_scope, f"hc_ev_eff_{index}"),
        ),
        "forecast_when_absent": labeled_checkbox(
            "Prognose bei Abwesenheit",
            value=bool(sched.get("forecast_when_absent", True)),
            key=_scoped_key(session_scope, f"hc_ev_forecast_{index}"),
        ),
        "nominal_power_voltage_v": labeled_number_input(
            "Nennspannung (V) für A→kW",
            min_value=100.0,
            max_value=500.0,
            value=float(sched.get("nominal_power_voltage_v", 230.0)),
            step=1.0,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_voltage_{index}"),
            help="Nur relevant, wenn der Lademerker Ampere liefert. Standard: 230 V.",
        ),
        "nominal_power_phases": labeled_number_input(
            "Phasen für A→kW",
            min_value=1,
            max_value=3,
            value=int(sched.get("nominal_power_phases", 1)),
            step=1,
            key=_scoped_key(session_scope, f"hc_ev_phases_{index}"),
            help="Standard: 1 Phase.",
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
    if _live_markers_enabled():
        st.caption(
            "E-Auto-Merker unter **Daemon Control → EHAL-Com** "
            "(Entity-Mapping) pflegen."
        )
    return item
