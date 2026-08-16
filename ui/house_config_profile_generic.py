"""Generic / Earnie-role consumer fields for Hausprofil form."""
from __future__ import annotations

from ui.house_config_profile_session import _scoped_key

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




_EARNIE_ROLE_LABELS = {
    EARNIE_ROLE_KNOWN: "Bekannt (Grundlast)",
    EARNIE_ROLE_FLEX: "Gesteuert (Optimierung)",
    EARNIE_ROLE_MANUAL: "Manuelles Gerät",
}

_EARNIE_ROLE_OPTIONS = [EARNIE_ROLE_KNOWN, EARNIE_ROLE_FLEX, EARNIE_ROLE_MANUAL]

def _schedule_defaults(sched: dict) -> dict:
    reject_legacy_start_flexibility(sched)
    raw_shift = sched.get("start_shift_h")
    coerced_shift = 12.0 if raw_shift is None else float(raw_shift)
    return {
        "duration_h": float(sched.get("duration_h", 2.0) or 2.0),
        "start_hour": int(sched.get("start_hour", DEFAULT_START_HOUR)) % 24,
        "start_shift_h": coerced_shift,
    }

def _loxone_inputs_from_consumer(consumer: dict) -> dict:
    inputs = consumer.get("loxone_inputs")
    if isinstance(inputs, dict):
        return dict(inputs)
    rec = consumer.get("appliance_recommendation") or {}
    legacy = str(rec.get("loxone_power_name", "")).strip()
    if legacy:
        return {"power_name": legacy}
    return {}

def _preserved_appliance_power_source(consumer: dict) -> str:
    """power_source from appliance_recommendation when Merker UI is hidden."""
    rec = consumer.get("appliance_recommendation") or {}
    source = str(rec.get("power_source", "") or "").strip().lower()
    if source in ("manual", "loxone"):
        return source
    if _loxone_inputs_from_consumer(consumer).get("power_name"):
        return "loxone"
    bindings = consumer.get("ehal_bindings")
    if isinstance(bindings, dict):
        from ehal.flex_fields import is_flex_sens_power_act_field

        if any(
            is_flex_sens_power_act_field(str(k)) and str(v or "").strip()
            for k, v in bindings.items()
        ):
            return "loxone"
    return "manual"

def _render_manual_power_source(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
) -> str:
    """Leistungsquelle without Merker text fields (bindings only via EHAL-Com)."""
    default_source = _preserved_appliance_power_source(consumer)
    power_source = labeled_selectbox(
        "Leistungsquelle",
        options=["manual", "loxone"],
        index=0 if default_source != "loxone" else 1,
        format_func=lambda value: (
            "Aus Profil (Nennleistung)" if value == "manual" else "Smarthome-Merker (EHAL-Com)"
        ),
        key=_scoped_key(session_scope, f"hc_app_src_{index}"),
    )
    if power_source == "loxone":
        st.caption(
            "Merker-Adresse unter **Daemon Control → EHAL-Com** "
            "(Entity-Mapping, Feld `flex.{id}.sens_power_act`) pflegen."
        )
    return power_source

def _render_manual_appliance_defaults(
    consumer: dict,
    index: int,
    nominal: float,
    duration_h: float,
    *,
    session_scope: str,
) -> dict:
    """Standard power/runtime for manual appliances (not Merker UI)."""
    rec = consumer.get("appliance_recommendation") or {}
    default_power = float(rec.get("default_power_kw", nominal) or nominal)
    default_runtime = float(rec.get("default_runtime_h", duration_h) or duration_h)
    return {
        "default_power_kw": float(
            labeled_number_input(
                "Standard-Leistung (kW)",
                min_value=0.0,
                value=default_power,
                key=_scoped_key(session_scope, f"hc_app_pwr_{index}"),
            )
        ),
        "default_runtime_h": float(
            labeled_number_input(
                "Standard-Laufzeit (h)",
                min_value=0.1,
                value=default_runtime,
                step=0.25,
                key=_scoped_key(session_scope, f"hc_app_rt_{index}"),
            )
        ),
    }

def _render_generic_flex_shift(
    defaults: dict,
    start_hour: int,
    index: int,
    *,
    session_scope: str,
) -> float:
    start_shift_h = labeled_number_input(
        "Verschiebung (± h)",
        min_value=0.5,
        max_value=MAX_START_SHIFT_H,
        value=max(0.5, min(MAX_START_SHIFT_H, defaults["start_shift_h"] or 12.0)),
        step=0.5,
        key=_scoped_key(session_scope, f"hc_shift_{index}"),
    )
    st.caption(format_start_window_caption(int(start_hour), float(start_shift_h)))
    st.caption("Bei 12 h Verschiebung ist der Startzeitpunkt vollständig frei.")
    return float(start_shift_h)


def _render_generic_manual_fields(
    consumer: dict,
    index: int,
    nominal: float,
    duration_h: float,
    defaults: dict,
    *,
    session_scope: str,
) -> tuple[float, dict]:
    horizon_default = (
        defaults["start_shift_h"]
        if defaults["start_shift_h"] >= 1
        else DEFAULT_MANUAL_HORIZON_H
    )
    start_shift_h = labeled_number_input(
        "Empfehlungshorizont (h)",
        min_value=1.0,
        max_value=MAX_START_SHIFT_H,
        value=min(MAX_START_SHIFT_H, float(horizon_default)),
        step=0.5,
        key=_scoped_key(session_scope, f"hc_horizon_{index}"),
    )
    st.caption(
        "Maximaler Vorschau-Horizont auf der Seite „Manuelle Geräte“ "
        "für die Startzeit-Empfehlung."
    )
    appliance_defaults = _render_manual_appliance_defaults(
        consumer,
        index,
        nominal,
        float(duration_h),
        session_scope=session_scope,
    )
    recommendation = {
        "power_source": _render_manual_power_source(
            consumer, index, session_scope=session_scope
        ),
        **appliance_defaults,
    }
    return float(start_shift_h), recommendation


def _render_generic_role_schedule(
    consumer: dict,
    index: int,
    nominal: float,
    item: dict,
    *,
    runs: int,
    earnie_role: str,
    defaults: dict,
    session_scope: str,
) -> dict:
    duration_h = labeled_number_input(
        "Nenndauer pro Lauf (h)",
        min_value=0.1,
        value=defaults["duration_h"],
        step=0.25,
        key=_scoped_key(session_scope, f"hc_duration_{index}"),
    )
    start_hour = labeled_number_input(
        "Referenz-Startzeit (Stunde)",
        min_value=0,
        max_value=23,
        value=defaults["start_hour"],
        ratios=WIDE_LABEL_RATIOS,
        key=_scoped_key(session_scope, f"hc_start_{index}"),
    )
    start_shift_h = 0.0
    if earnie_role == EARNIE_ROLE_FLEX:
        start_shift_h = _render_generic_flex_shift(
            defaults, int(start_hour), index, session_scope=session_scope
        )
    elif earnie_role == EARNIE_ROLE_MANUAL:
        start_shift_h, recommendation = _render_generic_manual_fields(
            consumer,
            index,
            nominal,
            float(duration_h),
            defaults,
            session_scope=session_scope,
        )
        item["appliance_recommendation"] = recommendation
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


def _render_generic_role_select(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
) -> str:
    current_role = resolve_earnie_role(consumer)
    if current_role not in _EARNIE_ROLE_OPTIONS:
        current_role = EARNIE_ROLE_KNOWN
    return labeled_selectbox(
        "Earnie-Berücksichtigung",
        options=_EARNIE_ROLE_OPTIONS,
        index=_EARNIE_ROLE_OPTIONS.index(current_role),
        format_func=lambda value: _EARNIE_ROLE_LABELS[value],
        key=_scoped_key(session_scope, f"hc_earnie_role_{index}"),
    )


def _generic_zero_runs_item(item: dict, earnie_role: str) -> dict:
    if earnie_role in (EARNIE_ROLE_FLEX, EARNIE_ROLE_MANUAL):
        st.warning(
            "Gesteuert / Manuelles Gerät: bitte Läufe pro Woche ≥ 1 setzen "
            "(oder Rolle Bekannt wählen und CSV nutzen)."
        )
    item["annual_kwh"] = 0.0
    return item


def _render_generic_fields(
    consumer: dict,
    index: int,
    nominal: float,
    *,
    session_scope: str,
) -> dict:
    sched = consumer.get("schedule") or {}
    defaults = _schedule_defaults(sched)
    st.caption(
        "**Läufe pro Woche = 0:** kein synthetisches Wochenmuster — nur sinnvoll für "
        "**Bekannt** mit aktivem CSV („Von Basis-Last abziehen“). "
        "Gesteuert / Manuelles Gerät brauchen mindestens 1 Lauf."
    )
    runs = labeled_number_input(
        "Läufe pro Woche",
        min_value=0,
        value=int(sched.get("runs_per_week", 0)),
        key=_scoped_key(session_scope, f"hc_runs_{index}"),
        help=(
            "0 = inaktiv / kein Wochenmuster. "
            "Nur bei Bekannt+CSV erlaubt; sonst ≥ 1."
        ),
    )
    earnie_role = _render_generic_role_select(
        consumer, index, session_scope=session_scope
    )
    item: dict = {
        "nominal_power_kw": nominal,
        "schedule": None,
        "earnie_role": earnie_role,
    }
    if runs <= 0:
        return _generic_zero_runs_item(item, earnie_role)
    return _render_generic_role_schedule(
        consumer,
        index,
        nominal,
        item,
        runs=runs,
        earnie_role=earnie_role,
        defaults=defaults,
        session_scope=session_scope,
    )
