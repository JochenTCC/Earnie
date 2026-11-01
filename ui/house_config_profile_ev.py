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
from house_config.profile_schema_defaults import consumer_default, ev_schedule_default
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
        "min_on_quarterhours": consumer_default("min_on_quarterhours", consumer_type="ev"),
        "battery_capacity_kwh": 60.0,
        "charging_schedule": {
            "target_soc_percent": ev_schedule_default("target_soc_percent"),
            "charging_efficiency": ev_schedule_default("charging_efficiency"),
            "forecast_when_absent": ev_schedule_default("forecast_when_absent"),
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
            "milp": _suggested_ev_milp(1.4),
        },
    }


def _suggested_ev_milp(min_power_kw: float) -> dict:
    from optimizer.eauto_milp import (
        SUGGESTED_TIE_BREAK_ON_EPSILON,
        SUGGESTED_TIE_BREAK_TIME_EPSILON,
        suggested_min_remaining_kwh,
    )

    return {
        "live_modus_a_min_remaining_kwh": suggested_min_remaining_kwh(min_power_kw),
        "tie_break_on_epsilon": SUGGESTED_TIE_BREAK_ON_EPSILON,
        "tie_break_time_epsilon": SUGGESTED_TIE_BREAK_TIME_EPSILON,
    }

def _seed_ev_defaults_on_type_switch(
    consumer: dict, index: int, *, session_scope: str
) -> dict:
    """On Typ → EV, seed widget keys with EV defaults (keep label/id)."""
    type_key = _scoped_key(session_scope, f"hc_type_{index}")
    selected = st.session_state.get(type_key, consumer.get("type", "generic"))
    if str(selected) != "ev" or str(consumer.get("type", "generic")) == "ev":
        return consumer

    from house_config.entity_id_lock import ID_LOCKED_KEY, ID_PROVISIONAL_LABEL_KEY

    defaults = _default_ev_consumer()
    seeded = dict(defaults)
    if consumer.get("label"):
        seeded["label"] = consumer["label"]
    if consumer.get("id"):
        seeded["id"] = consumer["id"]
    if ID_LOCKED_KEY in consumer:
        seeded[ID_LOCKED_KEY] = consumer[ID_LOCKED_KEY]
    provisional = str(consumer.get(ID_PROVISIONAL_LABEL_KEY) or "").strip()
    if provisional:
        seeded[ID_PROVISIONAL_LABEL_KEY] = provisional
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
        f"hc_ev_target_soc_{index}": float(sched.get("target_soc_percent", ev_schedule_default("target_soc_percent"))),
        f"hc_ev_eff_{index}": float(sched.get("charging_efficiency", ev_schedule_default("charging_efficiency"))),
        f"hc_ev_forecast_{index}": bool(sched.get("forecast_when_absent", ev_schedule_default("forecast_when_absent"))),
        f"hc_ev_Werktag_from_{index}": int(weekday.get("car_available_from_hour", 18)),
        f"hc_ev_Werktag_ready_{index}": int(weekday.get("ready_by_hour", 7)),
        f"hc_ev_Werktag_soc_{index}": float(weekday.get("daily_rest_soc", 40.0)),
        f"hc_ev_Wochenende_from_{index}": int(weekend.get("car_available_from_hour", 20)),
        f"hc_ev_Wochenende_ready_{index}": int(weekend.get("ready_by_hour", 9)),
        f"hc_ev_Wochenende_soc_{index}": float(weekend.get("daily_rest_soc", 30.0)),
    }
    milp = sched.get("milp") or {}
    values.update(
        {
            f"hc_ev_milp_rem_{index}": float(milp["live_modus_a_min_remaining_kwh"]),
            f"hc_ev_milp_eps_on_{index}": float(milp["tie_break_on_epsilon"]),
            f"hc_ev_milp_eps_time_{index}": float(milp["tie_break_time_epsilon"]),
        }
    )
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

def _render_ev_power_fields(consumer: dict, index: int, *, session_scope: str) -> dict:
    return {
        "min_power_kw": labeled_number_input(
            "Mindestleistung (kW)",
            min_value=0.0,
            value=float(consumer.get("min_power_kw", 1.4)),
            key=_scoped_key(session_scope, f"hc_ev_min_{index}"),
        ),
        "min_on_quarterhours": labeled_number_input(
            "Mindest-Ladedauer (Viertelstunden)",
            min_value=1,
            value=int(consumer.get("min_on_quarterhours", 1)),
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

def _render_ev_amp_conversion_fields(
    sched: dict, index: int, *, session_scope: str
) -> dict:
    """Nennspannung / Phasen — only used when the Lademerker delivers Ampere."""
    return {
        "nominal_power_voltage_v": labeled_number_input(
            "Nennspannung (V) für A→kW",
            min_value=100.0,
            max_value=500.0,
            value=float(sched.get("nominal_power_voltage_v", ev_schedule_default("nominal_power_voltage_v"))),
            step=1.0,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_voltage_{index}"),
            help="Nur relevant, wenn der Lademerker Ampere liefert. Standard: 230 V.",
        ),
        "nominal_power_phases": labeled_number_input(
            "Phasen für A→kW",
            min_value=1,
            max_value=3,
            value=int(sched.get("nominal_power_phases", ev_schedule_default("nominal_power_phases"))),
            step=1,
            key=_scoped_key(session_scope, f"hc_ev_phases_{index}"),
            help="Standard: 1 Phase.",
        ),
    }

def _render_ev_charging_schedule(
    sched: dict, index: int, *, session_scope: str
) -> dict:
    return {
        "target_soc_percent": labeled_number_input(
            "Ziel-SOC (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(sched.get("target_soc_percent", ev_schedule_default("target_soc_percent"))),
            key=_scoped_key(session_scope, f"hc_ev_target_soc_{index}"),
        ),
        "charging_efficiency": labeled_number_input(
            "Lade-Wirkungsgrad",
            min_value=0.01,
            max_value=1.0,
            value=float(sched.get("charging_efficiency", ev_schedule_default("charging_efficiency"))),
            step=0.01,
            key=_scoped_key(session_scope, f"hc_ev_eff_{index}"),
        ),
        "forecast_when_absent": labeled_checkbox(
            "Prognose, wenn nicht angeschlossen",
            value=bool(sched.get("forecast_when_absent", ev_schedule_default("forecast_when_absent"))),
            key=_scoped_key(session_scope, f"hc_ev_forecast_{index}"),
            help=(
                "Lade-Prognose ohne Wallbox-Anschluss (charging_schedule). "
                "Unabhängig vom Haus-Abwesenheitsmodus."
            ),
        ),
        **_render_ev_amp_conversion_fields(
            sched, index, session_scope=session_scope
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

def _render_ev_fields(consumer: dict, index: int, *, session_scope: str) -> dict:
    sched = dict(consumer.get("charging_schedule") or {})
    item: dict = _render_ev_power_fields(consumer, index, session_scope=session_scope)
    item["charging_schedule"] = _render_ev_charging_schedule(
        sched, index, session_scope=session_scope
    )
    item["charging_schedule"]["milp"] = _render_ev_milp_fields(
        sched.get("milp") or {},
        float(item["min_power_kw"]),
        index,
        session_scope=session_scope,
    )
    if _live_markers_enabled():
        st.caption(
            "E-Auto-Bindings unter **Daemon Control → EHAL-Com** "
            "(Entity-Mapping) pflegen."
        )
    return item


def _render_ev_milp_fields(
    milp: dict, min_power_kw: float, index: int, *, session_scope: str
) -> dict:
    """``charging_schedule.milp`` — required for live charging with a current setpoint."""
    suggested = _suggested_ev_milp(min_power_kw)
    st.markdown("**MILP-Feintuning**")
    st.caption(
        "Pflicht für die Live-Optimierung, wenn Earnie den Ladestrom vorgibt. "
        "Ohne gespeicherte Werte sind die Vorschläge eingetragen "
        "(Restmenge 2 × Mindestleistung); mit **Speichern** gelten sie."
    )
    return {
        "live_modus_a_min_remaining_kwh": labeled_number_input(
            "Kontinuierlich laden ab Restmenge (kWh)",
            min_value=0.001,
            value=float(
                milp.get(
                    "live_modus_a_min_remaining_kwh",
                    suggested["live_modus_a_min_remaining_kwh"],
                )
            ),
            step=0.1,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_milp_rem_{index}"),
            help=(
                "Liegt die noch zu ladende Energie darüber, gibt Earnie eine stetige "
                "Ladeleistung vor; darunter schaltet es in ganzen Viertelstunden "
                "(live_modus_a_min_remaining_kwh)."
            ),
        ),
        "tie_break_on_epsilon": labeled_number_input(
            "Tie-Break Einschalten (ε₁)",
            min_value=0.0,
            value=float(milp.get("tie_break_on_epsilon", suggested["tie_break_on_epsilon"])),
            step=0.0001,
            format="%.5f",
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_milp_eps_on_{index}"),
            help="Kleine Strafe je Lade-Viertelstunde; soll weit unter dem kleinsten Bezugspreis liegen.",
        ),
        "tie_break_time_epsilon": labeled_number_input(
            "Tie-Break Zeitpunkt (ε₂)",
            min_value=0.0,
            value=float(
                milp.get("tie_break_time_epsilon", suggested["tie_break_time_epsilon"])
            ),
            step=0.0001,
            format="%.5f",
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_milp_eps_time_{index}"),
            help="Kleine Strafe für spätes Laden; bei gleichen Kosten lädt Earnie früher.",
        ),
    }
