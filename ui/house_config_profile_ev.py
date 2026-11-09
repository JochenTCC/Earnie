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
from house_config.wallboxes import (
    ASSIGNMENT_FIXED,
    WALLBOX_ASSIGNMENT_KEY,
    assigned_wallbox_id,
    pair_limits,
)
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




# Car defaults of a new EV (1 phase, 6–16 A ≈ 1.4–3.7 kW at 230 V).
DEFAULT_EV_PHASES = 1
DEFAULT_EV_MIN_CURRENT_A = 6.0
DEFAULT_EV_MAX_CURRENT_A = 16.0
# Voltage of a wallbox the EV form creates (editable on the Wallboxen tab) and of the
# MILP suggestion while no wallbox is chosen.
NEW_WALLBOX_VOLTAGE_V = 230.0


def _pair_kw(current_a: float, *, voltage_v: float, phases: int) -> float:
    return float(current_a) * float(voltage_v) * int(phases) / 1000.0


def ev_form_pair(item: dict) -> dict | None:
    """Pair limits of the form's EV and its chosen wallbox; None without a usable pair."""
    from ui.house_config_wallbox_io import wallboxes_map

    wallbox = wallboxes_map().get(assigned_wallbox_id(item))
    if wallbox is None:
        return None
    try:
        return pair_limits(item, wallbox, label=str(item.get("label") or "E-Auto"))
    except ValueError:
        return None


def _default_ev_consumer() -> dict:
    return {
        "label": "E-Auto",
        "type": "ev",
        "phases": DEFAULT_EV_PHASES,
        "min_current_a": DEFAULT_EV_MIN_CURRENT_A,
        "max_current_a": DEFAULT_EV_MAX_CURRENT_A,
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
            "milp": _suggested_ev_milp(
                _pair_kw(
                    DEFAULT_EV_MIN_CURRENT_A,
                    voltage_v=NEW_WALLBOX_VOLTAGE_V,
                    phases=DEFAULT_EV_PHASES,
                )
            ),
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
        f"hc_ev_phases_{index}": int(seeded["phases"]),
        f"hc_ev_min_a_{index}": float(seeded["min_current_a"]),
        f"hc_ev_max_a_{index}": float(seeded["max_current_a"]),
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

def _wallbox_select_key(index: int, session_scope: str) -> str:
    return _scoped_key(session_scope, f"hc_ev_wallbox_{index}")


def _create_wallbox_for_ev(car: dict, *, select_key: str) -> None:
    """Button: a new wallbox with the car's limits at 230 V, chosen for this EV."""
    from ui.house_config_wallbox_io import upsert_wallbox

    label = f"Wallbox {str(car.get('label') or 'E-Auto').strip()}"
    try:
        wallbox_id = upsert_wallbox(
            {
                "label": label,
                "voltage_v": NEW_WALLBOX_VOLTAGE_V,
                "phases": car["phases"],
                "min_current_a": car["min_current_a"],
                "max_current_a": car["max_current_a"],
            }
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    st.session_state[f"{select_key}__pending"] = wallbox_id
    st.rerun()


def _render_wallbox_choice(consumer: dict, car: dict, index: int, *, session_scope: str) -> str:
    """Fixed wallbox of the EV (D3); empty when none exists yet."""
    from ui.house_config_wallbox_io import wallboxes_map

    wallboxes = wallboxes_map()
    key = _wallbox_select_key(index, session_scope)
    pending = st.session_state.pop(f"{key}__pending", None)
    if pending is not None:
        st.session_state[key] = pending
    if key in st.session_state and st.session_state[key] not in wallboxes:
        del st.session_state[key]
    wallbox_id = ""
    if wallboxes:
        ids = list(wallboxes)
        if key not in st.session_state:
            current = assigned_wallbox_id(consumer)
            st.session_state[key] = current if current in ids else ids[0]
        wallbox_id = str(
            labeled_selectbox(
                "Wallbox",
                options=ids,
                format_func=lambda wid: str(wallboxes[wid]["label"]),
                key=key,
                help="Feste Zuordnung: an dieser Wallbox lädt das Auto (Tab „Wallboxen“).",
            )
        )
    else:
        st.warning(
            "Noch keine Wallbox angelegt — das E-Auto wird erst mit einer Wallbox gespeichert."
        )
    if st.button(
        "Neue Wallbox für dieses E-Auto anlegen",
        key=_scoped_key(session_scope, f"hc_ev_new_wallbox_{index}"),
        help="Mit den Grenzen des Autos und 230 V; im Tab „Wallboxen“ anpassen.",
    ):
        _create_wallbox_for_ev({**consumer, **car}, select_key=key)
    return wallbox_id


def _render_pair_caption(item: dict) -> None:
    from ui.house_config_wallbox_io import wallboxes_map

    wallbox = wallboxes_map().get(assigned_wallbox_id(item))
    if wallbox is None:
        return
    try:
        limits = pair_limits(item, wallbox, label=str(item.get("label") or "E-Auto"))
    except ValueError as exc:
        st.error(str(exc))
        return
    st.caption(
        f"Wallbox: {wallbox['voltage_v']:g} V, {wallbox['phases']} Phase(n), "
        f"{wallbox['min_current_a']:g}–{wallbox['max_current_a']:g} A. "
        f"Geladen wird mit {limits['min_current_a']:g}–{limits['max_current_a']:g} A an "
        f"{limits['phases']} Phase(n): {limits['min_power_kw']:.2f} – "
        f"{limits['max_power_kw']:.2f} kW (gemeinsamer Bereich von Auto und Wallbox)."
    )


def _render_ev_power_fields(consumer: dict, index: int, *, session_scope: str) -> dict:
    """Car limits as current and the fixed wallbox (data model 6, D2 / D3)."""
    phases = int(
        labeled_number_input(
            "Phasen des Autos",
            min_value=1,
            max_value=3,
            value=int(consumer.get("phases", DEFAULT_EV_PHASES)),
            step=1,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_phases_{index}"),
            help="Phasen, mit denen das Auto laden kann (Bordlader).",
        )
    )
    min_a = float(
        labeled_number_input(
            "Mindest-Ladestrom des Autos (A)",
            min_value=0.0,
            value=float(consumer.get("min_current_a", DEFAULT_EV_MIN_CURRENT_A)),
            step=1.0,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_min_a_{index}"),
        )
    )
    max_a = float(
        labeled_number_input(
            "Höchst-Ladestrom des Autos (A)",
            min_value=0.0,
            value=float(consumer.get("max_current_a", DEFAULT_EV_MAX_CURRENT_A)),
            step=1.0,
            ratios=WIDE_LABEL_RATIOS,
            key=_scoped_key(session_scope, f"hc_ev_max_a_{index}"),
        )
    )
    car = {"phases": phases, "min_current_a": min_a, "max_current_a": max_a}
    wallbox_id = _render_wallbox_choice(consumer, car, index, session_scope=session_scope)
    item: dict = dict(car)
    if wallbox_id:
        item[WALLBOX_ASSIGNMENT_KEY] = {"mode": ASSIGNMENT_FIXED, "wallbox_id": wallbox_id}
        _render_pair_caption({**item, "label": consumer.get("label")})
    item.update(
        {
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
    )
    return item

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
    pair = ev_form_pair(item)
    item["charging_schedule"]["milp"] = _render_ev_milp_fields(
        sched.get("milp") or {},
        pair["min_power_kw"]
        if pair is not None
        else _pair_kw(
            item["min_current_a"], voltage_v=NEW_WALLBOX_VOLTAGE_V, phases=item["phases"]
        ),
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
        "Ohne gespeicherte Werte trägt das Formular die Vorschläge ein "
        "(Restmenge 2 × Mindestleistung) und speichert sie automatisch mit dem Hausprofil."
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
