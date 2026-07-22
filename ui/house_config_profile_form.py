"""Hausprofil-Tab im Hauskonfigurator."""
from __future__ import annotations

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
    migrate_start_flexibility,
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

CONSUMER_TYPE_OPTIONS = ["generic", "thermal_annual", "thermal_rc", "ev"]
_SESSION_SYNC_KEY = "house_profile_sync_id"
_SESSION_CONSUMERS_KEY = "house_profile_consumers"
_SESSION_SELECT_PENDING_KEY = "house_profile_select_pending"
_SESSION_SELECTED_ID_KEY = "house_profile_selected_id"
_NEW_PROFILE_OPTION = "— neu —"
_SESSION_FILE_STAMP_KEY = "house_profile_file_stamp"

_PASSTHROUGH_CONSUMER_KEYS = (
    "loxone_inputs",
    "loxone_outputs",
    "legacy_id",
    "optimizer_flex",
    "thermal_flex_window",
    "max_on_quarterhours",
    "max_pulses_per_day",
    "min_on_quarterhours",
    "heating_power_threshold_kw",
    "actual_temp_step_c",
    "thermal_control",
    "swimspa_filter_bindings",
    "profile_csv",
    "use_profile_csv",
)

_EARNIE_ROLE_LABELS = {
    EARNIE_ROLE_KNOWN: "Bekannt (Grundlast)",
    EARNIE_ROLE_FLEX: "Gesteuert (Optimierung)",
    EARNIE_ROLE_MANUAL: "Manuelles Gerät",
}
_EARNIE_ROLE_OPTIONS = [EARNIE_ROLE_KNOWN, EARNIE_ROLE_FLEX, EARNIE_ROLE_MANUAL]


def _merge_passthrough_consumer_fields(original: dict, edited: dict) -> dict:
    merged = dict(edited)
    for key in _PASSTHROUGH_CONSUMER_KEYS:
        if key not in original or key in merged:
            continue
        value = original[key]
        merged[key] = dict(value) if isinstance(value, dict) else value
    orig_sched = original.get("charging_schedule")
    if isinstance(orig_sched, dict):
        sched = dict(merged.get("charging_schedule") or {})
        sched_updated = False
        loxone = orig_sched.get("loxone")
        if isinstance(loxone, dict) and "loxone" not in sched:
            sched["loxone"] = dict(loxone)
            sched_updated = True
        milp = orig_sched.get("milp")
        if isinstance(milp, dict) and milp and "milp" not in sched:
            sched["milp"] = dict(milp)
            sched_updated = True
        if sched_updated:
            merged["charging_schedule"] = sched
    return merged


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
    from house_config.label_uniqueness import allocate_unique_label

    existing = list(st.session_state.get(_SESSION_CONSUMERS_KEY, []))
    return {
        "label": allocate_unique_label("Verbraucher", existing),
        "type": "generic",
        "nominal_power_kw": 1.0,
        "schedule": {
            "runs_per_week": 0,
        },
    }


def _schedule_defaults(sched: dict) -> dict:
    migrated = migrate_start_flexibility(dict(sched))
    raw_shift = migrated.get("start_shift_h")
    coerced_shift = 12.0 if raw_shift is None else float(raw_shift)
    return {
        "duration_h": float(migrated.get("duration_h", 2.0) or 2.0),
        "start_hour": int(migrated.get("start_hour", DEFAULT_START_HOUR)) % 24,
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


def _render_power_source_fields(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
    key_prefix: str,
) -> tuple[str, dict | None]:
    """Leistungsquelle + optional loxone_inputs.power_name."""
    from ui.smarthome_marker_fields import render_marker_text

    inputs = _loxone_inputs_from_consumer(consumer)
    rec = consumer.get("appliance_recommendation") or {}
    has_marker = bool(str(inputs.get("power_name", "")).strip())
    default_source = "loxone" if (
        str(rec.get("power_source", "")).lower() == "loxone" or has_marker
    ) else "manual"
    power_source = labeled_selectbox(
        "Leistungsquelle",
        options=["manual", "loxone"],
        index=0 if default_source != "loxone" else 1,
        format_func=lambda value: (
            "Aus Profil (Nennleistung)" if value == "manual" else "Smarthome-Merker"
        ),
        key=_scoped_key(session_scope, f"{key_prefix}_src_{index}"),
    )
    if power_source != "loxone":
        return power_source, None
    st.caption(
        "Merker-Adresse (Loxone Miniserver); für künftige Live-Adaption gespeichert. "
        "Grundlast/Empfehlung nutzen weiterhin Nennleistung aus dem Profil."
    )
    marker = render_marker_text(
        "Smarthome-Merker (Leistung)",
        inputs.get("power_name", ""),
        key=_scoped_key(session_scope, f"{key_prefix}_merker_{index}"),
    )
    return power_source, {"power_name": marker} if marker else None


def _render_live_io_markers(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
    key_prefix: str,
    include_enable: bool = True,
    include_ev_outputs: bool = False,
    include_subtract: bool = False,
) -> tuple[dict, dict]:
    """Edit loxone_inputs / loxone_outputs used by live consumers."""
    from ui.smarthome_marker_fields import render_marker_text

    st.markdown("**Smarthome-Merker (Live)**")
    st.caption("Rollen = Config-Schlüssel; Werte = Miniserver-Merkernamen (Loxone).")
    inputs = _loxone_inputs_from_consumer(consumer)
    outputs = dict(consumer.get("loxone_outputs") or {})
    power_name = render_marker_text(
        "Merker: Leistung (Lesen)",
        inputs.get("power_name", ""),
        key=_scoped_key(session_scope, f"{key_prefix}_pwr_{index}"),
    )
    new_inputs: dict = {}
    if power_name:
        new_inputs["power_name"] = power_name
    if "signal_type" in inputs:
        new_inputs["signal_type"] = inputs["signal_type"]
    if include_subtract:
        subtract = inputs.get("subtract_consumer_ids")
        existing = (
            ", ".join(str(item) for item in subtract)
            if isinstance(subtract, list)
            else ""
        )
        subtract_text = render_marker_text(
            "Abzug Verbraucher-IDs (Komma, optional)",
            existing,
            key=_scoped_key(session_scope, f"{key_prefix}_sub_{index}"),
        )
        if subtract_text:
            new_inputs["subtract_consumer_ids"] = [
                part.strip() for part in subtract_text.split(",") if part.strip()
            ]
    new_outputs: dict = {}
    if include_enable:
        enable_name = render_marker_text(
            "Merker: Freigabe (Schreiben)",
            outputs.get("enable_name", ""),
            key=_scoped_key(session_scope, f"{key_prefix}_en_{index}"),
        )
        if enable_name:
            new_outputs["enable_name"] = enable_name
    if include_ev_outputs:
        setpoint = render_marker_text(
            "Merker: Lade-Sollwert kW (Schreiben)",
            outputs.get("power_setpoint_name", ""),
            key=_scoped_key(session_scope, f"{key_prefix}_set_{index}"),
        )
        pv_follow = render_marker_text(
            "Merker: PV-Follow (Schreiben)",
            outputs.get("pv_follow_name", ""),
            key=_scoped_key(session_scope, f"{key_prefix}_pvf_{index}"),
        )
        if setpoint:
            new_outputs["power_setpoint_name"] = setpoint
        if pv_follow:
            new_outputs["pv_follow_name"] = pv_follow
    return new_inputs, new_outputs


def _render_ev_charging_loxone(
    sched: dict,
    index: int,
    *,
    session_scope: str,
) -> dict:
    from ui.smarthome_marker_fields import (
        EV_CHARGING_LOXONE_FIELDS,
        collect_named_markers,
    )

    st.markdown("**E-Auto Status-Merker** (`charging_schedule.loxone`)")
    source = sched.get("loxone") if isinstance(sched.get("loxone"), dict) else {}
    return collect_named_markers(
        source,
        EV_CHARGING_LOXONE_FIELDS,
        key_prefix=_scoped_key(session_scope, f"hc_ev_lox_{index}"),
    )


def _render_thermal_control_loxone(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
) -> dict:
    from ui.smarthome_marker_fields import (
        THERMAL_CONTROL_LOXONE_FIELDS,
        collect_named_markers,
    )

    st.markdown("**Temperatur-Merker** (`thermal_control.loxone`)")
    control = consumer.get("thermal_control") if isinstance(
        consumer.get("thermal_control"), dict
    ) else {}
    source = control.get("loxone") if isinstance(control.get("loxone"), dict) else {}
    loxone = collect_named_markers(
        source,
        THERMAL_CONTROL_LOXONE_FIELDS,
        key_prefix=_scoped_key(session_scope, f"hc_tc_lox_{index}"),
    )
    return {"loxone": loxone} if loxone else {}


def _render_swimspa_filter_bindings(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
) -> dict:
    """Optional marker overrides for bridge-only SwimSpa filter."""
    from house_config.planning_flex_bridge import SWIMSPA_FILTER_BRIDGE_DEFAULTS
    from ui.smarthome_marker_fields import (
        assemble_filter_bindings,
        filter_binding_prefills,
        render_marker_text,
    )

    st.markdown("**SwimSpa-Filter Merker** (optional, Bridge-Defaults)")
    st.caption(
        "Overrides für den Bridge-Filter; leer = eingebauter Default. "
        "Kein eigener Hausprofil-Verbraucher."
    )
    stored = consumer.get("swimspa_filter_bindings")
    stored = stored if isinstance(stored, dict) else {}
    prefills = filter_binding_prefills(stored, SWIMSPA_FILTER_BRIDGE_DEFAULTS)
    prefix = _scoped_key(session_scope, f"hc_filt_{index}")
    labels = (
        ("loxone_target_hours_name", "Merker: Filter-Sollstunden", "hours"),
        ("power_name", "Merker: Filter Leistung/Aktiv", "pwr"),
        ("alternate_binary_power_name", "Merker: Filter alternativ", "alt"),
        ("enable_name", "Merker: Filter Freigabe", "en"),
        ("native_start_hour_name", "Merker: natives Filter-Start", "start"),
        ("native_duration_hours_name", "Merker: natives Filter-Dauer", "dur"),
    )
    values = {
        role: render_marker_text(label, prefills.get(role, ""), key=f"{prefix}_{suffix}")
        for role, label, suffix in labels
    }
    return assemble_filter_bindings(values)


def _render_manual_appliance_fields(
    consumer: dict,
    index: int,
    nominal: float,
    duration_h: float,
    *,
    session_scope: str,
) -> tuple[dict, dict | None]:
    rec = consumer.get("appliance_recommendation") or {}
    power_source, loxone_inputs = _render_power_source_fields(
        consumer,
        index,
        session_scope=session_scope,
        key_prefix="hc_app",
    )
    default_power = float(rec.get("default_power_kw", nominal) or nominal)
    default_runtime = float(rec.get("default_runtime_h", duration_h) or duration_h)
    default_power_kw = labeled_number_input(
        "Standard-Leistung (kW)",
        min_value=0.0,
        value=default_power,
        key=_scoped_key(session_scope, f"hc_app_pwr_{index}"),
    )
    default_runtime_h = labeled_number_input(
        "Standard-Laufzeit (h)",
        min_value=0.1,
        value=default_runtime,
        step=0.25,
        key=_scoped_key(session_scope, f"hc_app_rt_{index}"),
    )
    block: dict = {
        "power_source": power_source,
        "default_power_kw": float(default_power_kw),
        "default_runtime_h": float(default_runtime_h),
    }
    return block, loxone_inputs


def _render_generic_fields(
    consumer: dict,
    index: int,
    nominal: float,
    *,
    session_scope: str,
) -> dict:
    sched = consumer.get("schedule") or {}
    defaults = _schedule_defaults(sched)
    runs = labeled_number_input(
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
    current_role = resolve_earnie_role(consumer)
    if current_role not in _EARNIE_ROLE_OPTIONS:
        current_role = EARNIE_ROLE_KNOWN
    earnie_role = labeled_selectbox(
        "Earnie-Berücksichtigung",
        options=_EARNIE_ROLE_OPTIONS,
        index=_EARNIE_ROLE_OPTIONS.index(current_role),
        format_func=lambda value: _EARNIE_ROLE_LABELS[value],
        key=_scoped_key(session_scope, f"hc_earnie_role_{index}"),
    )
    item["earnie_role"] = earnie_role
    start_shift_h = 0.0
    if earnie_role == EARNIE_ROLE_FLEX:
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
    elif earnie_role == EARNIE_ROLE_MANUAL:
        horizon_default = defaults["start_shift_h"] if defaults["start_shift_h"] >= 1 else DEFAULT_MANUAL_HORIZON_H
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
        appliance_rec, loxone_inputs = _render_manual_appliance_fields(
            consumer,
            index,
            nominal,
            float(duration_h),
            session_scope=session_scope,
        )
        item["appliance_recommendation"] = appliance_rec
        item["loxone_inputs"] = loxone_inputs or {}
    elif earnie_role == EARNIE_ROLE_KNOWN:
        _, loxone_inputs = _render_power_source_fields(
            consumer,
            index,
            session_scope=session_scope,
            key_prefix="hc_known",
        )
        item["loxone_inputs"] = loxone_inputs or {}
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


def _seed_profile_widget_state(
    session_scope: str,
    existing: dict,
    *,
    siblings: list[dict] | None = None,
) -> None:
    from house_config.label_uniqueness import allocate_unique_label

    if existing:
        label = str(existing.get("label", "Mein Haushalt"))
        annual_kwh = float(existing.get("annual_kwh", 4500.0))
        latitude = float(existing.get("latitude", 48.2))
        longitude = float(existing.get("longitude", 11.0))
        default_pv_tilt = int(existing.get("default_pv_tilt", 25))
        default_pv_azimuth = int(existing.get("default_pv_azimuth", 0))
    else:
        label = allocate_unique_label("Mein Haushalt", siblings or [])
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


def _sync_profile_session(
    session_scope: str,
    existing: dict,
    *,
    file_stamp: str,
    siblings: list[dict] | None = None,
) -> list[dict]:
    scope_changed = st.session_state.get(_SESSION_SYNC_KEY) != session_scope
    file_changed = st.session_state.get(_SESSION_FILE_STAMP_KEY) != file_stamp
    widget_state_missing = _profile_widget_state_missing(session_scope)
    if scope_changed or file_changed or widget_state_missing:
        _clear_scoped_widget_keys(session_scope)
        _seed_profile_widget_state(session_scope, existing, siblings=siblings)
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
        item = _merge_passthrough_consumer_fields(original, dict(item))
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
    loxone_inputs, loxone_outputs = _render_live_io_markers(
        consumer,
        index,
        session_scope=session_scope,
        key_prefix="hc_ev_io",
        include_enable=False,
        include_ev_outputs=True,
    )
    item["loxone_inputs"] = loxone_inputs
    item["loxone_outputs"] = loxone_outputs
    charging_loxone = _render_ev_charging_loxone(
        sched, index, session_scope=session_scope
    )
    if charging_loxone:
        item["charging_schedule"]["loxone"] = charging_loxone
    return item


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
    col_a, col_b = st.columns(2)
    with col_a:
        latitude = labeled_number_input(
            "Breitengrad",
            format="%.4f",
            key=_scoped_key(session_scope, "house_profile_latitude"),
        )
    with col_b:
        longitude = labeled_number_input(
            "Längengrad",
            format="%.4f",
            key=_scoped_key(session_scope, "house_profile_longitude"),
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
    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "timezone_name": timezone_name,
        "default_pv_tilt": float(default_pv_tilt),
        "default_pv_azimuth": float(default_pv_azimuth),
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
    loxone_inputs, loxone_outputs = _render_live_io_markers(
        consumer,
        index,
        session_scope=session_scope,
        key_prefix="hc_rc_io",
        include_enable=True,
        include_subtract=True,
    )
    item["loxone_inputs"] = loxone_inputs
    item["loxone_outputs"] = loxone_outputs
    thermal_control = _render_thermal_control_loxone(
        consumer, index, session_scope=session_scope
    )
    if thermal_control:
        item["thermal_control"] = thermal_control
    filter_bindings = _render_swimspa_filter_bindings(
        consumer, index, session_scope=session_scope
    )
    if filter_bindings:
        item["swimspa_filter_bindings"] = filter_bindings
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


def _consumer_expander_title(consumer: dict, index: int, *, session_scope: str) -> str:
    """Prefer live Bezeichnung widget state so expander header updates for every type."""
    label_key = _scoped_key(session_scope, f"hc_label_{index}")
    live = st.session_state.get(label_key)
    if live is None:
        live = consumer.get("label")
    title = str(live or "").strip() or f"Verbraucher {index + 1}"
    return f"Verbraucher {index + 1}: {title}"


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
    expander_title = _consumer_expander_title(
        consumer, index, session_scope=session_scope
    )
    # Expand first consumer only when it has no saved id yet (new/empty form).
    has_saved_data = bool(str(consumer.get("id") or "").strip())
    # Stable key keeps open/closed state across Bezeichnung title changes + auto_persist rerun.
    with st.expander(
        expander_title,
        expanded=index == 0 and not has_saved_data,
        key=_scoped_key(session_scope, f"hc_consumer_expander_{index}"),
    ):
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
        c_type = labeled_selectbox(
            "Typ",
            options=type_options,
            index=_type_index(current_type, type_options),
            format_func=lambda value: CONSUMER_TYPE_LABELS.get(value, value),
            key=_scoped_key(session_scope, f"hc_type_{index}"),
        )
        c_label = labeled_text_input(
            "Bezeichnung",
            value=consumer.get("label", ""),
            key=_scoped_key(session_scope, f"hc_label_{index}"),
        )
        nominal = labeled_number_input(
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
        elif c_type == "thermal_rc":
            item.update(_render_thermal_rc_fields(consumer, index, session_scope=session_scope))
        else:
            thermal = consumer.get("thermal") or consumer
            item["min_on_quarterhours"] = labeled_number_input(
                "Mindestlaufzeit (Viertelstunden)",
                min_value=0,
                value=int(consumer.get("min_on_quarterhours", 4)),
                ratios=WIDE_LABEL_RATIOS,
                key=_scoped_key(session_scope, f"hc_ta_min_qh_{index}"),
            )
            item["living_area_m2"] = labeled_number_input(
                "Wohnfläche (m²)",
                min_value=0.0,
                value=float(thermal.get("living_area_m2", 120.0)),
                key=_scoped_key(session_scope, f"hc_area_{index}"),
            )
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
            loxone_inputs, loxone_outputs = _render_live_io_markers(
                consumer,
                index,
                session_scope=session_scope,
                key_prefix="hc_ta_io",
                include_enable=True,
            )
            item["loxone_inputs"] = loxone_inputs
            item["loxone_outputs"] = loxone_outputs
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
        item.update(
            _render_consumer_profile_csv_fields(
                consumer,
                index,
                session_scope=session_scope,
                nominal_power_kw=float(nominal),
            )
        )
    return item


def _digital_csv_decision_key(session_scope: str, index: int, path: str) -> str:
    return _scoped_key(session_scope, f"hc_digital_csv_decision_{index}_{path}")


def _ensure_consumer_csv_normalized(
    path: str,
    *,
    digital_scale_kw: float | None = None,
) -> None:
    from house_config.consumption_csv import load_hourly_profile_csv, normalize_profile_csv_file

    if digital_scale_kw is not None:
        normalize_profile_csv_file(path, digital_scale_kw=digital_scale_kw)
        return
    try:
        load_hourly_profile_csv(path)
    except ValueError:
        normalize_profile_csv_file(path)


def _render_digital_csv_scale_prompt(
    path: str,
    *,
    index: int,
    session_scope: str,
    nominal_power_kw: float,
) -> None:
    """Ask once whether to multiply a digital 0/1 CSV by nominal power."""
    from house_config.consumption_csv import profile_csv_looks_digital

    decision_key = _digital_csv_decision_key(session_scope, index, path)
    decision = st.session_state.get(decision_key)
    if decision == "yes":
        return
    if decision == "no":
        try:
            _ensure_consumer_csv_normalized(path)
        except (ValueError, OSError, FileNotFoundError) as exc:
            st.warning(f"CSV noch nicht normalisierbar: {exc}")
        return
    try:
        looks_digital = profile_csv_looks_digital(path)
    except (ValueError, OSError, FileNotFoundError) as exc:
        st.warning(f"CSV noch nicht normalisierbar: {exc}")
        return
    if not looks_digital:
        try:
            _ensure_consumer_csv_normalized(path)
        except (ValueError, OSError, FileNotFoundError) as exc:
            st.warning(f"CSV noch nicht normalisierbar: {exc}")
        return
    st.info(
        f"Digitales Ein/Aus-Signal (0/1) erkannt. "
        f"Mit Nennleistung **{nominal_power_kw:.3f} kW** multiplizieren?"
    )
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button(
            "Ja, mit Nennleistung multiplizieren",
            key=_scoped_key(session_scope, f"hc_digital_yes_{index}"),
        ):
            if nominal_power_kw <= 0.0:
                st.error("Nennleistung muss > 0 kW sein, um zu skalieren.")
            else:
                try:
                    _ensure_consumer_csv_normalized(
                        path, digital_scale_kw=nominal_power_kw
                    )
                    st.session_state[decision_key] = "yes"
                    st.success(
                        f"CSV mit {nominal_power_kw:.3f} kW skaliert und gespeichert."
                    )
                    st.rerun()
                except (ValueError, OSError, FileNotFoundError) as exc:
                    st.error(f"Skalierung fehlgeschlagen: {exc}")
    with col_no:
        if st.button(
            "Nein, Werte unverändert lassen",
            key=_scoped_key(session_scope, f"hc_digital_no_{index}"),
        ):
            try:
                _ensure_consumer_csv_normalized(path)
                st.session_state[decision_key] = "no"
                st.rerun()
            except (ValueError, OSError, FileNotFoundError) as exc:
                st.error(f"Normalisierung fehlgeschlagen: {exc}")


def _render_consumer_profile_csv_fields(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
    nominal_power_kw: float,
) -> dict:
    """Historisches Verbraucher-CSV + use_profile_csv-Flag."""
    from pathlib import Path

    st.markdown("**Historisches Verbrauchsprofil (CSV)**")
    st.caption(
        "Gleiches Format wie Jahres-CSV (`timestamp;power_kw`). "
        "Wenn aktiv: echtes Profil statt Synthese, Abzug von der Gesamt-CSV. "
        "Digitale 0/1-Signale: beim Import optional × Nennleistung."
    )
    path_key = _scoped_key(session_scope, f"hc_profile_csv_path_{index}")
    input_key = _scoped_key(session_scope, f"hc_profile_csv_input_{index}")
    use_key = _scoped_key(session_scope, f"hc_use_profile_csv_{index}")
    pending_key = _scoped_key(session_scope, f"hc_profile_csv_pending_{index}")
    upload_base = _scoped_key(session_scope, f"hc_profile_csv_upload_{index}")
    upload_nonce_key = _scoped_key(session_scope, f"hc_profile_csv_upload_nonce_{index}")
    flash_key = _scoped_key(session_scope, f"hc_profile_csv_flash_{index}")

    apply_csv_path_pending(pending_key, path_key, input_key, use_key=use_key)
    if path_key not in st.session_state:
        st.session_state[path_key] = str(consumer.get("profile_csv", "") or "").strip()
    if input_key not in st.session_state:
        st.session_state[input_key] = st.session_state[path_key]

    flash = st.session_state.pop(flash_key, None)
    if flash:
        st.success(flash)

    csv_path = labeled_text_input(
        "CSV-Pfad (Verbraucher)",
        value=st.session_state[path_key],
        key=input_key,
    )
    st.session_state[path_key] = csv_path.strip()
    upload = single_csv_upload(
        "Verbraucher-CSV hochladen",
        key=csv_upload_widget_key(upload_base, upload_nonce_key),
        help="Nur eine CSV-Datei je Verbraucher.",
    )
    consumer_slug = slug_id(str(consumer.get("id") or consumer.get("label") or f"c{index}"))
    profile_slug = slug_id(
        str(
            st.session_state.get(_SESSION_SELECTED_ID_KEY)
            or st.session_state.get("house_profile_select")
            or "profile"
        )
    )
    if upload is not None:
        try:
            saved = save_profile_consumption_csv(
                profile_slug,
                upload.getvalue(),
                upload.name,
                consumer_id=consumer_slug or f"c{index}",
            )
            decision_key = _digital_csv_decision_key(session_scope, index, saved)
            st.session_state.pop(decision_key, None)
            queue_csv_path_update(
                pending_key,
                saved,
                upload_nonce_key=upload_nonce_key,
                flash_key=flash_key,
                flash_message=f"CSV gespeichert: `{saved}`",
            )
            st.rerun()
        except (ValueError, OSError, FileNotFoundError) as exc:
            st.error(f"CSV ungültig: {exc}")
    if st.button(
        "Verbraucher-CSV entfernen",
        key=_scoped_key(session_scope, f"hc_profile_csv_clear_{index}"),
    ):
        queue_csv_path_update(
            pending_key,
            "",
            upload_nonce_key=upload_nonce_key,
        )
        st.rerun()
    active = st.session_state[path_key]
    if active:
        from runtime_store.persist_paths import resolve_config_prefixed_path

        if Path(resolve_config_prefixed_path(active)).is_file():
            _render_digital_csv_scale_prompt(
                active,
                index=index,
                session_scope=session_scope,
                nominal_power_kw=nominal_power_kw,
            )
    if active:
        use_csv = labeled_checkbox(
            "Aus Gesamt-CSV abziehen / echtes Profil nutzen",
            value=bool(consumer.get("use_profile_csv", False)),
            key=use_key,
            help="Aktiv: CSV-Last statt Synthese; Abzug von total_profile_csv für die Rest-Grundlast.",
        )
    else:
        st.session_state[use_key] = False
        use_csv = False
    return {
        "profile_csv": active,
        "use_profile_csv": bool(use_csv),
    }


def _profile_display_label(profile_map: dict, profile_id: str) -> str:
    return str(profile_map.get(profile_id, {}).get("label") or profile_id)


def _profile_select_choices(
    profile_map: dict, profile_ids: list[str]
) -> tuple[list[str], dict[str, str]]:
    """Build selectbox options from live labels (not format_func) so UI refreshes."""
    displays = [_NEW_PROFILE_OPTION]
    id_by_display = {_NEW_PROFILE_OPTION: _NEW_PROFILE_OPTION}
    for profile_id in profile_ids:
        display = _profile_display_label(profile_map, profile_id)
        if display in id_by_display:
            display = f"{display} ({profile_id})"
        displays.append(display)
        id_by_display[display] = profile_id
    return displays, id_by_display


def _align_profile_select_session(
    profile_map: dict,
    profile_ids: list[str],
    id_by_display: dict[str, str],
) -> None:
    """Rewrite selectbox session value when Bezeichnung/labels change on disk."""
    current = st.session_state.get("house_profile_select")
    if current is not None and str(current) in id_by_display:
        mapped = id_by_display[str(current)]
        if mapped != _NEW_PROFILE_OPTION:
            st.session_state[_SESSION_SELECTED_ID_KEY] = mapped
        return

    selected_id = st.session_state.get(_SESSION_SELECTED_ID_KEY)
    if selected_id in profile_ids:
        st.session_state["house_profile_select"] = _profile_display_label(
            profile_map, str(selected_id)
        )
        return
    if current is not None and str(current) in profile_ids:
        st.session_state[_SESSION_SELECTED_ID_KEY] = str(current)
        st.session_state["house_profile_select"] = _profile_display_label(
            profile_map, str(current)
        )


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
    from house_config.consumption_csv import consumer_uses_profile_csv
    from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display

    st.subheader("Verbrauchsprofil (Modell)")
    st.caption("Modelliertes Hausprofil — ohne Ist-CSV und ohne cons_data.")
    view_mode = st.radio(
        "Anzeige",
        options=["all", "csv_only"],
        format_func=lambda value: (
            "Alle Verbraucher"
            if value == "all"
            else "Nur CSV-instrumentierte Verbraucher"
        ),
        horizontal=True,
        key=f"house_profile_model_view_{preview_id}",
    )
    consumers = list(resolved)
    if view_mode == "csv_only":
        consumers = [c for c in consumers if consumer_uses_profile_csv(c)]
        if not consumers:
            st.info(
                "Keine Verbraucher mit aktivem historischen CSV "
                "(`use_profile_csv`). Wechseln Sie zu „Alle Verbraucher“ "
                "oder laden Sie ein CSV und aktivieren Sie den Abzug."
            )
            return
    modeled_profile = {
        "annual_kwh": annual_kwh,
        "baseload_kwh": preview["baseload_kwh"],
        "consumers": consumers,
        # Intentionally omit total_profile_csv: Modell uses metric baseload, not meter residual.
    }
    reset_token = (
        f"{preview_id}:{view_mode}:{annual_kwh:.0f}:{preview['consumer_kwh']:.0f}:"
        f"{preview['baseload_kwh']:.0f}:{len(consumers)}"
    )
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
    from ui.house_config_historical_csv import render_historical_csv_section

    render_historical_csv_section(
        existing=existing,
        preview_id=preview_id,
        annual_kwh=annual_kwh,
        resolved=resolved,
        preview=preview,
    )


def _perform_house_profile_save(
    *,
    is_new: bool,
    stable_profile_id: str,
    label: str,
    profile_ids: list[str],
    annual_kwh: float,
    location: dict,
    resolved: list[dict],
    existing: dict,
    preview_id: str,
    from_auto: bool = False,
) -> str | None:
    profile_id = _resolve_profile_id(
        is_new=is_new,
        existing_id=stable_profile_id,
        label=label,
        profile_ids=set(profile_ids),
    )
    try:
        from ui.house_config_historical_csv import historical_csv_save_fields

        hist = historical_csv_save_fields(preview_id, existing)
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
                "total_profile_csv": hist["total_profile_csv"],
                "pv_profile_csv": hist["pv_profile_csv"],
                "historical_csv_source": hist["historical_csv_source"],
            }
        )
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.session_state[_SESSION_FILE_STAMP_KEY] = _house_profiles_file_stamp()
    if is_new:
        saved_profile = load_house_profiles().get("profiles", {}).get(profile_id, {})
        st.session_state[_SESSION_SELECT_PENDING_KEY] = profile_id
        st.session_state[_SESSION_SYNC_KEY] = None
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(saved_profile)
        st.rerun()
    elif not from_auto:
        saved_profile = load_house_profiles().get("profiles", {}).get(profile_id, {})
        st.session_state[_SESSION_SELECT_PENDING_KEY] = profile_id
        st.session_state[_SESSION_SYNC_KEY] = None
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(saved_profile)
        st.success("Profil gespeichert.")
        st.rerun()
    return profile_id


def _render_house_profile_save(
    *,
    session_scope: str,
    is_new: bool,
    stable_profile_id: str,
    label: str,
    profile_ids: list[str],
    annual_kwh: float,
    location: dict,
    resolved: list[dict],
    existing: dict,
    preview_id: str,
) -> None:
    from ui.auto_persist import auto_persist
    from ui.house_config_historical_csv import historical_csv_save_fields

    ready = bool(str(label or "").strip()) and location.get("latitude") is not None
    if not ready:
        return
    hist = historical_csv_save_fields(preview_id, existing)
    profile_id = _resolve_profile_id(
        is_new=is_new,
        existing_id=stable_profile_id,
        label=label,
        profile_ids=set(profile_ids),
    )
    payload = {
        "id": profile_id,
        "label": label.strip() or profile_id,
        "annual_kwh": float(annual_kwh),
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "default_pv_tilt": location["default_pv_tilt"],
        "default_pv_azimuth": location["default_pv_azimuth"],
        "consumers": resolved,
        "total_profile_csv": hist["total_profile_csv"],
        "pv_profile_csv": hist["pv_profile_csv"],
        "historical_csv_source": hist["historical_csv_source"],
    }

    def _save() -> None:
        _perform_house_profile_save(
            is_new=is_new,
            stable_profile_id=stable_profile_id,
            label=label,
            profile_ids=profile_ids,
            annual_kwh=annual_kwh,
            location=location,
            resolved=resolved,
            existing=existing,
            preview_id=preview_id,
            from_auto=True,
        )

    wrote = auto_persist(
        state_key=f"house_profile::{session_scope}::{profile_id}",
        payload=payload,
        save=_save,
        ready=ready,
    )
    # Refresh Profil dropdown labels from disk (auto-save previously skipped st.rerun).
    if wrote:
        st.rerun()


def render_house_profile_tab() -> None:
    _apply_pending_profile_select()
    profiles_doc = load_house_profiles()
    profile_map = profiles_doc.get("profiles", {})
    profile_ids = sorted(profile_map.keys())
    profile_options, id_by_display = _profile_select_choices(profile_map, profile_ids)
    _align_profile_select_session(profile_map, profile_ids, id_by_display)
    initial_index = _initial_profile_index(profile_ids)

    if initial_index is not None:
        selected_display = labeled_selectbox(
            "Profil",
            options=profile_options,
            index=initial_index,
            key="house_profile_select",
        )
    else:
        selected_display = labeled_selectbox(
            "Profil",
            options=profile_options,
            key="house_profile_select",
        )
    selected_id = id_by_display.get(str(selected_display), str(selected_display))
    is_new = selected_id == _NEW_PROFILE_OPTION
    existing = profile_map.get(selected_id, {}) if not is_new else {}
    stable_profile_id = str(existing.get("id", "")).strip()
    session_scope = _profile_session_scope(selected_id, is_new=is_new)
    if not is_new:
        st.session_state[_SESSION_SELECTED_ID_KEY] = selected_id
    file_stamp = _house_profiles_file_stamp()
    _sync_profile_session(
        session_scope,
        existing,
        file_stamp=file_stamp,
        siblings=list(profile_map.values()),
    )

    label = labeled_text_input(
        "Bezeichnung",
        key=_scoped_key(session_scope, "house_profile_label"),
    )
    preview_id = _resolve_profile_id(
        is_new=is_new,
        existing_id=stable_profile_id,
        label=label,
        profile_ids=set(profile_ids),
    )

    annual_kwh = labeled_number_input(
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
    # Keep session list Bezeichnung/type in sync so titles stay correct after save.
    synced_consumers = []
    for index, original in enumerate(consumers):
        merged = dict(original)
        if index < len(edited):
            merged["label"] = edited[index].get("label", original.get("label"))
            merged["type"] = edited[index].get("type", original.get("type"))
        synced_consumers.append(merged)
    st.session_state[_SESSION_CONSUMERS_KEY] = synced_consumers
    resolved = _resolve_consumer_ids(synced_consumers, edited)
    resolved_for_preview = _inject_profile_geo(
        resolved,
        location["latitude"],
        location["longitude"],
        timezone_name=str(location.get("timezone_name") or ""),
    )
    preview = preview_baseload(annual_kwh, resolved_for_preview)
    csv_session_key = f"house_profile_csv_path_{preview_id}"
    preview["total_profile_csv"] = str(
        st.session_state.get(
            csv_session_key,
            existing.get("total_profile_csv", ""),
        )
        or ""
    ).strip()
    st.metric("Verbraucher-Summe (kWh/a)", f"{preview['consumer_kwh']:.0f}")
    st.metric("Grundlast (kWh/a)", f"{preview['baseload_kwh']:.0f}")
    st.caption(
        f"Roh-Differenz {preview['raw_baseload_kwh']:.0f} kWh/a; "
        f"Untergrenze 2 % = {preview['baseload_min_kwh']:.0f} kWh/a"
    )

    _render_house_profile_save(
        session_scope=session_scope,
        is_new=is_new,
        stable_profile_id=stable_profile_id,
        label=label,
        profile_ids=profile_ids,
        annual_kwh=float(annual_kwh),
        location=location,
        resolved=resolved,
        existing=existing,
        preview_id=preview_id,
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

    _render_house_profile_save(
        session_scope=session_scope,
        is_new=is_new,
        stable_profile_id=stable_profile_id,
        label=label,
        profile_ids=profile_ids,
        annual_kwh=float(annual_kwh),
        location=location,
        resolved=resolved,
        existing=existing,
        preview_id=preview_id,
    )
