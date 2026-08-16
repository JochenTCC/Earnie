"""Hausprofil consumers → MILP flex shapes (generic / EV / thermal / pool)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from settings.ev_power import merge_ev_power_conversion_fields
from settings.flexible_consumers import reject_legacy_id
from house_config.consumption_csv import consumer_uses_profile_csv
from house_config.earnie_role import is_earnie_flex, is_earnie_known, is_earnie_manual

if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext

POOL_FILTER_ID = "pool_filter"


def _attach_ehal_bindings(result: dict, consumer: dict) -> None:
    """Copy house-profile ``ehal_bindings`` onto MILP flex shape (Live write markers)."""
    bindings = consumer.get("ehal_bindings")
    if isinstance(bindings, dict) and bindings:
        result["ehal_bindings"] = dict(bindings)


def _generic_live_signal_type(consumer: dict, result: dict) -> str:
    """Live meter type for generic MILP flex (manual/flex).

    MILP itself stays on/off. Live/Chart must use kW when a Zähler is bound;
    otherwise 0/1 × Nennleistung.
    """
    explicit = str(
        ((consumer.get("loxone_inputs") or {}).get("signal_type"))
        or consumer.get("signal_type")
        or ""
    ).strip().lower()
    if explicit in ("power", "binary"):
        return explicit
    from settings.ehal_marker_resolve import marker_flex_power

    if marker_flex_power(result) or marker_flex_power(consumer):
        return "power"
    power_name = str(
        ((consumer.get("loxone_inputs") or {}).get("power_name") or "")
    ).strip()
    if power_name:
        return "power"
    return "binary"


def _apply_live_signal_type(consumer: dict, result: dict) -> None:
    live_signal = _generic_live_signal_type(consumer, result)
    result["signal_type"] = live_signal
    result["log_signal_type"] = live_signal
    if live_signal != "power":
        return
    inputs = dict(result.get("loxone_inputs") or {})
    inputs["signal_type"] = "power"
    result["loxone_inputs"] = inputs


def is_milp_pool_filter(consumer: dict) -> bool:
    """True for the house-profile Pool/SwimSpa filter row (MILP Sollstunden path)."""
    return str(consumer.get("id") or "").strip() == POOL_FILTER_ID


def _house_generic_consumers(house_profile: dict) -> list[dict]:
    """Generic consumers with a schedule, or known+CSV (schedule optional).

    ``pool_filter`` is excluded — it is MILP-only via ``planning_pool_filter_to_milp``.
    """
    out: list[dict] = []
    for consumer in house_profile.get("consumers", []):
        if consumer.get("type") != "generic":
            continue
        if is_milp_pool_filter(consumer):
            continue
        if consumer.get("schedule"):
            out.append(consumer)
        elif is_earnie_known(consumer) and consumer_uses_profile_csv(consumer):
            out.append(consumer)
    return out


def split_planning_generic_consumers(
    house_profile: dict,
) -> tuple[list[dict], list[dict]]:
    """Split generic consumers into fixed overlay vs MILP flex.

    ``known`` feeds the fixed baseload overlay. ``flex`` and ``manual`` are
    MILP-flex (manual timing optimized in SE; Live uses user day-plans only).
    ``pool_filter`` is excluded here — it uses ``planning_pool_filter_to_milp``.
    """
    fixed: list[dict] = []
    flex: list[dict] = []
    for consumer in _house_generic_consumers(house_profile):
        if is_earnie_known(consumer):
            fixed.append(consumer)
        elif is_earnie_flex(consumer) or is_earnie_manual(consumer):
            if not consumer.get("schedule"):
                continue
            flex.append(planning_consumer_to_milp(consumer))
    return fixed, flex


def planning_consumer_to_milp(consumer: dict) -> dict:
    schedule = consumer["schedule"]
    duration_h = float(schedule["duration_h"])
    min_on_quarterhours = max(4, int(round(duration_h * 4)))
    nominal = float(consumer["nominal_power_kw"])
    result = {
        "id": str(consumer["id"]),
        "name": str(consumer.get("label", consumer["id"])),
        "nominal_power_kw": nominal,
        "min_power_kw": nominal,
        "min_on_quarterhours": min_on_quarterhours,
        "daily_target_kwh": 0.0,
        "daily_target_source": "config",
        "signal_type": "binary",
        "log_signal_type": "binary",
        "optimizer_enabled": True,
        "generic_flex_window": {
            "start_hour": int(schedule["start_hour"]) % 24,
            "start_shift_h": float(schedule.get("start_shift_h", 0.0) or 0.0),
            "duration_h": duration_h,
        },
        "loxone_outputs": {},
        "loxone_inputs": {},
    }
    loxone_inputs = consumer.get("loxone_inputs")
    if isinstance(loxone_inputs, dict) and loxone_inputs:
        result["loxone_inputs"] = dict(loxone_inputs)
    loxone_outputs = consumer.get("loxone_outputs")
    if isinstance(loxone_outputs, dict) and loxone_outputs:
        result["loxone_outputs"] = dict(loxone_outputs)
    _attach_ehal_bindings(result, consumer)
    _apply_live_signal_type(consumer, result)
    return result


def _house_ev_consumers(house_profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in house_profile.get("consumers", [])
        if consumer.get("type") == "ev" and consumer.get("charging_schedule")
    ]


def planning_ev_to_milp(consumer: dict) -> dict:
    """Hausprofil-EV → flexible_consumers-Shape für MILP; Live-Loxone aus Profil."""
    sched = consumer["charging_schedule"]
    min_on = max(1, int(consumer.get("min_on_quarterhours", 4) or 4))
    min_power = float(consumer.get("min_power_kw", 0.0) or 0.0)
    capacity = float(consumer["battery_capacity_kwh"])
    charging_schedule = merge_ev_power_conversion_fields(
        {
            "enabled": True,
            "forecast_when_absent": bool(sched.get("forecast_when_absent", True)),
            "target_soc_percent": float(sched.get("target_soc_percent", 100.0)),
            "charging_efficiency": float(sched.get("charging_efficiency", 0.95)),
            "weekday": dict(sched.get("weekday") or {}),
            "weekend": dict(sched.get("weekend") or {}),
            "battery_capacity_kwh": capacity,
        },
        sched,
    )
    sched_loxone = sched.get("loxone")
    if isinstance(sched_loxone, dict) and sched_loxone:
        charging_schedule["loxone"] = dict(sched_loxone)
    milp_raw = sched.get("milp")
    if isinstance(milp_raw, dict) and milp_raw:
        charging_schedule["milp"] = dict(milp_raw)
    result = {
        "id": str(consumer["id"]),
        "name": str(consumer.get("label", consumer["id"])),
        "nominal_power_kw": float(consumer["nominal_power_kw"]),
        "min_power_kw": min_power if min_power > 0 else None,
        "min_on_quarterhours": min_on,
        "signal_type": "power",
        "log_signal_type": "power",
        "optimizer_enabled": True,
        "daily_target_kwh": 0.0,
        "daily_target_source": "config",
        "battery_capacity_kwh": capacity,
        "charging_schedule": charging_schedule,
        "path_historical_log": "",
        "loxone_outputs": {},
        "loxone_inputs": {},
        "loxone_target_kwh_name": "",
        "loxone_target_hours_name": "",
    }
    loxone_inputs = consumer.get("loxone_inputs")
    if isinstance(loxone_inputs, dict) and loxone_inputs:
        result["loxone_inputs"] = dict(loxone_inputs)
    loxone_outputs = consumer.get("loxone_outputs")
    if isinstance(loxone_outputs, dict) and loxone_outputs:
        result["loxone_outputs"] = dict(loxone_outputs)
    setpoint_name = str((result.get("loxone_outputs") or {}).get("power_setpoint_name", "")).strip()
    if setpoint_name and not charging_schedule.get("milp"):
        raise ValueError(
            f"Hausprofil-EV '{consumer['id']}': charging_schedule.milp fehlt "
            "(live_modus_a_min_remaining_kwh, tie_break_on_epsilon, tie_break_time_epsilon) — "
            "Pflicht bei loxone_outputs.power_setpoint_name."
        )
    reject_legacy_id(consumer, str(consumer["id"]))
    _attach_ehal_bindings(result, consumer)
    return result


def planning_ev_consumers(house_profile: dict) -> list[dict]:
    """EV-Verbraucher aus Hausprofil als MILP-flexible Verbraucher."""
    return [planning_ev_to_milp(consumer) for consumer in _house_ev_consumers(house_profile)]


def _house_thermal_rc_consumers(house_profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in house_profile.get("consumers", [])
        if consumer.get("type") == "thermal_rc"
    ]


def _thermal_rc_params(consumer: dict) -> dict:
    nested = consumer.get("thermal_rc")
    if isinstance(nested, dict):
        return nested
    return consumer


def planning_thermal_rc_to_milp(consumer: dict) -> dict:
    """Hausprofil thermal_rc → MILP-flex mit thermal_control (Loxone via legacy overlay)."""
    rc = _thermal_rc_params(consumer)
    min_on = max(4, int(consumer.get("min_on_quarterhours", 8) or 8))
    reject_legacy_id(consumer, str(consumer["id"]))
    entry = {
        "id": str(consumer["id"]),
        "name": str(consumer.get("label", consumer["id"])),
        "nominal_power_kw": float(consumer.get("nominal_power_kw", 2.8) or 2.8),
        "min_on_quarterhours": min_on,
        "daily_target_kwh": 0.0,
        "daily_target_source": "thermal",
        "signal_type": "power",
        "log_signal_type": "power",
        "optimizer_enabled": True,
        "path_historical_log": "",
        "loxone_outputs": {},
        "loxone_inputs": {},
        "thermal_control": {
            "enabled": True,
            "mode": "active",
            "setpoint_c": float(rc["setpoint_c"]),
            "tolerance_c": float(rc["tolerance_c"]),
            "water_volume_liters": float(rc["water_volume_liters"]),
            "heat_loss_kw_per_k": float(rc["heat_loss_kw_per_k"]),
            "heating_efficiency": float(rc["heating_efficiency"]),
            "heating_power_threshold_kw": float(
                consumer.get("heating_power_threshold_kw", 2.0) or 2.0
            ),
            "actual_temp_step_c": float(consumer.get("actual_temp_step_c", 0.5) or 0.5),
            "loxone": {},
            "history_logs": {},
        },
    }
    heat_paths = rc.get("heat_paths")
    if isinstance(heat_paths, list) and heat_paths:
        entry["thermal_control"]["heat_paths"] = heat_paths
    loxone_inputs = consumer.get("loxone_inputs")
    if isinstance(loxone_inputs, dict) and loxone_inputs:
        entry["loxone_inputs"] = dict(loxone_inputs)
    loxone_outputs = consumer.get("loxone_outputs")
    if isinstance(loxone_outputs, dict) and loxone_outputs:
        entry["loxone_outputs"] = dict(loxone_outputs)
    profile_loxone = (consumer.get("thermal_control") or {}).get("loxone")
    if isinstance(profile_loxone, dict) and profile_loxone:
        entry["thermal_control"]["loxone"] = dict(profile_loxone)
    _attach_ehal_bindings(entry, consumer)
    return entry


def _pool_filter_schedule(consumer: dict) -> dict:
    """Build ``filter_schedule`` from profile row or weekly schedule fallback."""
    stored = consumer.get("filter_schedule")
    if isinstance(stored, dict) and stored:
        schedule = dict(stored)
        fallback = dict(schedule.get("config_fallback") or {})
        sched = consumer.get("schedule") if isinstance(consumer.get("schedule"), dict) else {}
        if "native_start_hour" not in fallback and sched.get("start_hour") is not None:
            fallback["native_start_hour"] = int(sched["start_hour"]) % 24
        if "native_duration_hours" not in fallback and sched.get("duration_h") is not None:
            fallback["native_duration_hours"] = float(sched["duration_h"])
        if fallback:
            schedule["config_fallback"] = fallback
        schedule.setdefault("enabled", True)
        return schedule
    sched = consumer.get("schedule") if isinstance(consumer.get("schedule"), dict) else {}
    start = int(sched.get("start_hour", 10) or 10) % 24
    duration = float(sched.get("duration_h", 4.0) or 4.0)
    return {
        "enabled": True,
        "config_fallback": {
            "native_start_hour": start,
            "native_duration_hours": duration,
        },
    }


def _pool_filter_daily_target_kwh(consumer: dict, nominal: float) -> float:
    raw = consumer.get("daily_target_kwh")
    if raw is not None:
        try:
            return round(float(raw), 3)
        except (TypeError, ValueError):
            pass
    sched = consumer.get("schedule") if isinstance(consumer.get("schedule"), dict) else {}
    duration = float(sched.get("duration_h", 0.0) or 0.0)
    if duration > 0 and nominal > 0:
        return round(nominal * duration, 3)
    return round(nominal * 2.0, 3) if nominal > 0 else 0.0


def planning_pool_filter_to_milp(consumer: dict) -> dict:
    """House-profile ``pool_filter`` → MILP flex (Sollstunden / native window)."""
    from settings.ehal_marker_resolve import marker_get_filter_remaining_hours

    nominal = float(consumer.get("nominal_power_kw", 0.18) or 0.18)
    min_on = max(1, int(consumer.get("min_on_quarterhours", 2) or 2))
    entry = {
        "id": POOL_FILTER_ID,
        "name": str(consumer.get("label") or consumer.get("name") or "Pool Filter"),
        "nominal_power_kw": nominal,
        "daily_target_kwh": _pool_filter_daily_target_kwh(consumer, nominal),
        "daily_target_source": "loxone_remaining_hours",
        "signal_type": str(consumer.get("signal_type") or "binary"),
        "min_on_quarterhours": min_on,
        "optimizer_enabled": bool(consumer.get("optimizer_enabled", True)),
        "path_historical_log": str(consumer.get("path_historical_log") or ""),
        "ehal_bindings": {},
        "filter_schedule": _pool_filter_schedule(consumer),
    }
    _attach_ehal_bindings(entry, consumer)
    hours = marker_get_filter_remaining_hours(entry)
    ehal = dict(entry.get("ehal_bindings") or {})
    if hours and not str(ehal.get("get_filter_remaining_hours") or "").strip():
        ehal["get_filter_remaining_hours"] = hours
    entry["ehal_bindings"] = ehal
    return entry


def _house_pool_filter_consumer(house_profile: dict) -> dict | None:
    for consumer in house_profile.get("consumers") or []:
        if isinstance(consumer, dict) and is_milp_pool_filter(consumer):
            return consumer
    return None


def planning_thermal_rc_consumers(house_profile: dict) -> list[dict]:
    return [planning_thermal_rc_to_milp(consumer) for consumer in _house_thermal_rc_consumers(house_profile)]


def _ensure_shared_meter_filter_subtract(heat: dict, filter_id: str) -> None:
    """Fall B: shared SwimSpa meter includes filter — subtract filter from heating Ist."""
    fid = str(filter_id or "").strip()
    if not fid:
        return
    inputs = dict(heat.get("loxone_inputs") or {})
    existing = [
        str(item).strip()
        for item in (inputs.get("subtract_consumer_ids") or [])
        if str(item).strip()
    ]
    if fid not in existing:
        existing.append(fid)
    inputs["subtract_consumer_ids"] = existing
    heat["loxone_inputs"] = inputs


def _house_thermal_consumers(house_profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in house_profile.get("consumers", [])
        if consumer.get("type") == "thermal_annual"
    ]


def thermal_optimizer_flex_enabled(consumer: dict) -> bool:
    """True wenn thermal_annual über MILP statt PWM-Overlay laufen soll."""
    if consumer.get("type") != "thermal_annual":
        return False
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    if nominal <= 0.0:
        return False
    if "optimizer_flex" in consumer:
        return bool(consumer["optimizer_flex"])
    return True


def planning_thermal_to_milp(consumer: dict) -> dict:
    """Hausprofil thermal_annual → MILP-binary mit HDD-Tagesziel (Thermals P1a)."""
    from house_config.thermal_labels import CONSUMER_TYPE_LABELS

    min_on = max(4, int(consumer.get("min_on_quarterhours", 4) or 4))
    nominal = float(consumer["nominal_power_kw"])
    entry: dict = {
        "id": str(consumer["id"]),
        "name": CONSUMER_TYPE_LABELS["thermal_annual"],
        "nominal_power_kw": nominal,
        "min_power_kw": nominal,
        "min_on_quarterhours": min_on,
        "max_on_quarterhours": int(consumer.get("max_on_quarterhours", 16) or 16),
        "max_pulses_per_day": int(consumer.get("max_pulses_per_day", 4) or 4),
        "daily_target_kwh": 0.0,
        "daily_target_source": "thermal_annual",
        "signal_type": "binary",
        "log_signal_type": "binary",
        "optimizer_enabled": True,
        "path_historical_log": "",
        "loxone_outputs": {},
        "loxone_inputs": {},
    }
    window = consumer.get("thermal_flex_window")
    if isinstance(window, dict) and window:
        entry["thermal_flex_window"] = dict(window)
    loxone_inputs = consumer.get("loxone_inputs")
    if isinstance(loxone_inputs, dict) and loxone_inputs:
        entry["loxone_inputs"] = dict(loxone_inputs)
    loxone_outputs = consumer.get("loxone_outputs")
    if isinstance(loxone_outputs, dict) and loxone_outputs:
        entry["loxone_outputs"] = dict(loxone_outputs)
    reject_legacy_id(consumer, str(consumer["id"]))
    _attach_ehal_bindings(entry, consumer)
    _apply_live_signal_type(consumer, entry)
    return entry


def planning_thermal_consumers(house_profile: dict) -> list[dict]:
    return [
        planning_thermal_to_milp(consumer)
        for consumer in _house_thermal_consumers(house_profile)
        if thermal_optimizer_flex_enabled(consumer)
    ]


def collect_planning_flex_consumers(house_profile: dict) -> list[dict]:
    """Generic MILP-flex + EV + thermal_annual + thermal_rc + optional pool_filter.

    thermal_rc with use_profile_csv is not MILP-flex: CSV load goes into the
    baseload overlay instead (historical replay, no double-counting).
    Filter is included only when an explicit ``pool_filter`` consumer exists.
    """
    _fixed, flex_generic = split_planning_generic_consumers(house_profile)
    thermal_rc_rows = _house_thermal_rc_consumers(house_profile)
    thermal_rc_flex = [
        planning_thermal_rc_to_milp(consumer)
        for consumer in thermal_rc_rows
        if not consumer_uses_profile_csv(consumer)
    ]
    pool = _house_pool_filter_consumer(house_profile)
    filters = [planning_pool_filter_to_milp(pool)] if pool is not None else []
    if filters and thermal_rc_flex:
        for heat in thermal_rc_flex:
            _ensure_shared_meter_filter_subtract(heat, POOL_FILTER_ID)
    return (
        flex_generic
        + planning_ev_consumers(house_profile)
        + planning_thermal_consumers(house_profile)
        + thermal_rc_flex
        + filters
    )


def _consumer_window_kwh(
    consumer: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> float:
    """Sum modeled/CSV power over planning slots as energy (kWh)."""
    from data.consumption_profiles import modeled_consumer_kw_at_datetime
    from optimizer.slot_duration import energy_kwh_from_kw

    return energy_kwh_from_kw(
        modeled_consumer_kw_at_datetime(consumer, slot_dt, climate=climate) or 0.0
        for slot_dt in slot_datetimes
    )


def milp_flex_thermal_annual_ids(flex_consumers: list[dict] | None) -> set[str]:
    if not flex_consumers:
        return set()
    return {
        str(consumer["id"])
        for consumer in flex_consumers
        if consumer.get("daily_target_source") == "thermal_annual"
    }


def _house_profile_consumer_ids(house_profile: dict) -> set[str]:
    return {
        str(consumer.get("id") or "")
        for consumer in house_profile.get("consumers", [])
        if consumer.get("id")
    }
