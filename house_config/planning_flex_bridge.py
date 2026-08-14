"""Brücke Hausprofil-generic → Backtesting (fixe Blöcke + MILP-Flex)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from settings.ev_power import merge_ev_power_conversion_fields
from settings.flexible_consumers import CONSUMER_PALETTE_SIZE, reject_legacy_id
from house_config.consumption_csv import consumer_uses_profile_csv
from house_config.earnie_role import is_earnie_flex, is_earnie_known, is_earnie_manual
from house_config.generic_schedule import (
    generic_daily_target_kwh_for_day,
)
from house_config.profile_csv_policy import se_uses_meter_residual_baseload


if TYPE_CHECKING:
    from data.modeled_climate import ModeledClimateContext

PROFILE_SPEC = "profile_spec"
LOGGED_DAY = "logged_day"
CONSUMPTION_SOURCES = frozenset({PROFILE_SPEC, LOGGED_DAY})


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


def resolve_consumption_source(scenario_params: dict | None) -> str:
    """profile_spec = Hausprofil-Spec für Optimierung; logged_day = cons_data-Replay."""
    if not scenario_params:
        return LOGGED_DAY
    explicit = str(scenario_params.get("consumption_source", "") or "").strip()
    if explicit in CONSUMPTION_SOURCES:
        return explicit
    if scenario_params.get("_house_profile"):
        return PROFILE_SPEC
    return LOGGED_DAY


def profile_flat_baseload_kw(house_profile: dict) -> float:
    """Konstante Grundlast (kW) aus profile.baseload_kwh."""
    return float(house_profile.get("baseload_kwh", 0.0) or 0.0) / 8760.0


def monthly_residual_baseload_kw(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Path A monthly: per-month Ist − Σ model consumers, mapped onto slots.

    Months missing from Gesamt-CSV fall back to flat ``baseload_kwh/8760``.
    """
    from house_config.baseload import (
        baseload_month_key,
        monthly_baseload_kw_by_month,
    )
    from house_config.consumption_csv import load_hourly_profile_csv
    from data.consumption_profiles import modeled_consumer_kw_at_datetime

    csv_path = str(house_profile.get("total_profile_csv", "") or "").strip()
    if not csv_path:
        raise ValueError("monthly residual requires total_profile_csv")
    rows = list(load_hourly_profile_csv(csv_path))
    if not rows:
        flat = profile_flat_baseload_kw(house_profile)
        return [round(flat, 6)] * len(slot_datetimes)
    timestamps = [ts for ts, _ in rows]
    ist_kw = [float(kw) for _, kw in rows]
    consumers = list(house_profile.get("consumers", []))
    consumer_kw = [
        sum(
            float(
                modeled_consumer_kw_at_datetime(
                    consumer,
                    datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
                    climate=climate,
                )
                or 0.0
            )
            for consumer in consumers
        )
        for ts in timestamps
    ]
    month_map = monthly_baseload_kw_by_month(timestamps, ist_kw, consumer_kw)
    flat = profile_flat_baseload_kw(house_profile)
    return [
        round(month_map.get(baseload_month_key(slot_dt), flat), 6)
        for slot_dt in slot_datetimes
    ]

POOL_FILTER_ID = "pool_filter"


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


def planning_ev_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    window_end: datetime | None = None,
) -> dict[str, float]:
    """Window kWh for EV flex — same power-capped schedule as cons_data / Historisch.

    SOC-only ``ev_daily_kwh`` can exceed what ``nominal_power_kw`` delivers in the
    charging window; using slot-modeled energy keeps profile_spec Jahres Verbrauch
    aligned with synthetic Historisch (same pattern as thermal_annual).
    """
    ev_by_id = {
        consumer["id"]: consumer
        for consumer in _house_ev_consumers(house_profile)
    }
    if not ev_by_id:
        return {}
    targets: dict[str, float] = {}
    for milp_consumer in flex_consumers:
        source = ev_by_id.get(milp_consumer["id"])
        if not source:
            continue
        targets[milp_consumer["id"]] = _consumer_window_kwh(source, slot_datetimes)
    return targets


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


def planning_thermal_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> dict[str, float]:
    """Window kWh for thermal_annual flex (slot-aligned, not full calendar days).

    Sunset/24h windows often span two calendar dates. Summing
    ``thermal_daily_kwh_for_date`` per touched date roughly doubles WP energy
    vs cons_data / hourly synthesis. Always use slot-hour energy instead.
    """
    by_id = {
        str(consumer["id"]): consumer
        for consumer in _house_thermal_consumers(house_profile)
    }
    targets: dict[str, float] = {}
    for milp_consumer in flex_consumers:
        if milp_consumer.get("daily_target_source") != "thermal_annual":
            continue
        source = by_id.get(milp_consumer["id"])
        if not source:
            continue
        targets[milp_consumer["id"]] = _consumer_window_kwh(
            source, slot_datetimes, climate=climate
        )
    return targets


def planning_thermal_rc_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> dict[str, float]:
    """Window kWh for non-CSV thermal_rc MILP-flex (CSV thermal_rc uses overlay)."""
    by_id = {
        str(consumer["id"]): consumer
        for consumer in _house_thermal_rc_consumers(house_profile)
    }
    targets: dict[str, float] = {}
    for milp_consumer in flex_consumers:
        if milp_consumer.get("daily_target_source") != "thermal":
            continue
        source = by_id.get(str(milp_consumer["id"]))
        if not source or consumer_uses_profile_csv(source):
            continue
        targets[str(milp_consumer["id"])] = _consumer_window_kwh(
            source, slot_datetimes, climate=climate
        )
    return targets


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


def _consumer_ids_with_cons_data(
    house_profile: dict,
    historical_totals: dict[str, float] | None = None,
    *,
    cons_data_consumer_ids: set[str] | None = None,
) -> set[str]:
    """Verbraucher-IDs, deren kWh bereits aus cons_data-Spalten stammen."""
    house_ids = _house_profile_consumer_ids(house_profile)
    if cons_data_consumer_ids is not None:
        return house_ids & cons_data_consumer_ids

    present: set[str] = set()
    totals = historical_totals or {}
    for cid in house_ids:
        if float(totals.get(cid, 0.0) or 0.0) > 0.0:
            present.add(cid)
    return present


def thermal_hourly_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    skip_consumer_ids: set[str] | None = None,
    milp_flex_thermal_ids: set[str] | None = None,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Summiert kW thermischer Verbraucher je Slot (annual + CSV thermal_rc)."""
    thermal_annual = _house_thermal_consumers(house_profile)
    thermal_rc_csv = [
        consumer
        for consumer in _house_thermal_rc_consumers(house_profile)
        if consumer_uses_profile_csv(consumer)
    ]
    thermal = list(thermal_annual) + thermal_rc_csv
    if not thermal:
        return [0.0] * len(slot_datetimes)
    from data.consumption_profiles import modeled_consumer_kw_at_datetime

    skip = skip_consumer_ids or set()
    milp_skip = milp_flex_thermal_ids or set()
    active = [
        consumer
        for consumer in thermal
        if str(consumer.get("id") or "") not in skip
        and str(consumer.get("id") or "") not in milp_skip
    ]
    if not active:
        return [0.0] * len(slot_datetimes)
    overlay: list[float] = []
    for slot_dt in slot_datetimes:
        kw = sum(
            modeled_consumer_kw_at_datetime(consumer, slot_dt, climate=climate)
            for consumer in active
        )
        overlay.append(round(kw, 6))
    return overlay


def house_profile_baseload_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    historical_totals: dict[str, float] | None = None,
    cons_data_consumer_ids: set[str] | None = None,
    milp_flex_thermal_ids: set[str] | None = None,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Fixe generic- und thermische Verbraucher aus Hausprofil je Slot."""
    skip_ids = _consumer_ids_with_cons_data(
        house_profile,
        historical_totals,
        cons_data_consumer_ids=cons_data_consumer_ids,
    )
    generic = fixed_generic_hourly_overlay(
        house_profile,
        slot_datetimes,
        skip_ids=skip_ids,
        meter_residual_mode=se_uses_meter_residual_baseload(house_profile),
    )
    thermal = thermal_hourly_overlay(
        house_profile,
        slot_datetimes,
        skip_consumer_ids=skip_ids,
        milp_flex_thermal_ids=milp_flex_thermal_ids,
        climate=climate,
    )
    return [round(g + t, 6) for g, t in zip(generic, thermal)]


def fixed_generic_hourly_overlay(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    skip_ids: set[str] | None = None,
    meter_residual_mode: bool | None = None,
) -> list[float]:
    """Summiert kW fixer generic-Verbraucher je Slot (CSV wins over schedule).

    In meter-residual mode (path B), known without CSV stay inside residual —
    do not also overlay their weekly schedule.
    """
    fixed, _flex = split_planning_generic_consumers(house_profile)
    if not fixed:
        return [0.0] * len(slot_datetimes)
    use_residual = (
        se_uses_meter_residual_baseload(house_profile)
        if meter_residual_mode is None
        else bool(meter_residual_mode)
    )
    skip = skip_ids or set()
    from data.consumption_profiles import modeled_consumer_kw_at_datetime

    overlay = [0.0] * len(slot_datetimes)
    for slot_index, slot_dt in enumerate(slot_datetimes):
        for consumer in fixed:
            cid = str(consumer.get("id") or "")
            if cid in skip:
                continue
            if use_residual and not consumer_uses_profile_csv(consumer):
                continue
            overlay[slot_index] += float(
                modeled_consumer_kw_at_datetime(consumer, slot_dt) or 0.0
            )
    return overlay


def meter_residual_baseload_kw(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> tuple[list[float], int]:
    """Path B: hourly residual = total_profile_csv − Σ(accounted CSV series).

    Controllable CSVs are peeled (MILP re-adds). Known CSV peeled and re-added
    via fixed overlay. Returns (residual_kw, clipped_hours).
    """
    from house_config.consumption_csv import load_hourly_profile_csv
    from house_config.profile_csv_policy import accounted_csv_consumers
    from data.consumption_profiles import (
        csv_kw_at_datetime,
        modeled_consumer_kw_at_datetime,
    )

    csv_path = str(house_profile.get("total_profile_csv", "") or "").strip()
    if not csv_path:
        raise ValueError("meter residual requires total_profile_csv")
    lookup = {ts: float(kw) for ts, kw in load_hourly_profile_csv(csv_path)}
    accounted = accounted_csv_consumers(house_profile)
    residual: list[float] = []
    clipped = 0
    for slot_dt in slot_datetimes:
        key = slot_dt.strftime("%Y-%m-%d %H:%M:%S")
        naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
        total = float(lookup.get(key, lookup.get(naive.strftime("%Y-%m-%d %H:%M:%S"), 0.0)))
        peel = 0.0
        for consumer in accounted:
            if consumer_uses_profile_csv(consumer):
                peel += float(csv_kw_at_datetime(consumer["profile_csv"], slot_dt) or 0.0)
            else:
                peel += float(
                    modeled_consumer_kw_at_datetime(
                        consumer, slot_dt, climate=climate
                    )
                    or 0.0
                )
        value = total - peel
        if value < 0.0:
            clipped += 1
            value = 0.0
        residual.append(round(value, 6))
    return residual, clipped


def planning_flex_daily_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    window_end: datetime | None = None,
) -> dict[str, float]:
    """Tagesziele (kWh) für Planungs-Flex-Verbraucher im Fenster.

    With ``use_profile_csv``, use CSV window energy; otherwise schedule energy.
    """
    if not flex_consumers:
        return {}
    from house_config.generic_schedule import (
        generic_daily_target_kwh_for_day,
        generic_flex_target_kwh_for_window,
    )

    by_id = {consumer["id"]: consumer for consumer in _house_generic_consumers(house_profile)}
    # Also map flex/manual that only have schedule via full consumer list
    for consumer in house_profile.get("consumers", []):
        if consumer.get("type") == "generic" and consumer.get("id"):
            by_id.setdefault(consumer["id"], consumer)
    targets: dict[str, float] = {}
    dates = {slot_dt.date() for slot_dt in slot_datetimes}
    anchor = window_end or (slot_datetimes[-1] + timedelta(hours=1) if slot_datetimes else None)
    for milp_consumer in flex_consumers:
        source = by_id.get(milp_consumer["id"])
        if not source:
            continue
        if consumer_uses_profile_csv(source):
            targets[milp_consumer["id"]] = _consumer_window_kwh(source, slot_datetimes)
            continue
        if anchor is not None:
            total = generic_flex_target_kwh_for_window(source, slot_datetimes, anchor)
        else:
            total = sum(
                generic_daily_target_kwh_for_day(source, day)
                for day in dates
            )
        targets[milp_consumer["id"]] = round(total, 3)
    return targets


def profile_reference_hourly_load(
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    climate: ModeledClimateContext | None = None,
) -> list[float]:
    """Stündlicher Referenz-Gesamtlast (kW) aus Hausprofil-Default-Schedules."""
    from data.consumption_profiles import modeled_consumer_kw_at_datetime
    from house_config.profile_csv_policy import se_uses_monthly_baseload

    if se_uses_monthly_baseload(house_profile):
        baseload_series = monthly_residual_baseload_kw(
            house_profile,
            slot_datetimes,
            climate=climate,
        )
    else:
        flat_kw = profile_flat_baseload_kw(house_profile)
        baseload_series = [flat_kw] * len(slot_datetimes)
    loads: list[float] = []
    for slot_dt, base_kw in zip(slot_datetimes, baseload_series):
        flex_sum = sum(
            modeled_consumer_kw_at_datetime(consumer, slot_dt, climate=climate)
            for consumer in house_profile.get("consumers", [])
        )
        loads.append(round(base_kw + flex_sum, 3))
    return loads

def tariff_reference_fingerprint(scenario_params: dict | None) -> tuple:
    """Vergleichsschlüssel für Referenz-Tarife (Import/Export)."""
    if not scenario_params:
        return ()
    import_spec = scenario_params.get("_import_tariff_spec")
    export_spec = scenario_params.get("_export_tariff_spec")
    return (
        import_spec.get("id") if isinstance(import_spec, dict) else None,
        export_spec.get("id") if isinstance(export_spec, dict) else None,
        scenario_params.get("import_tariff_type"),
        scenario_params.get("import_fixed_cent_kwh"),
        scenario_params.get("feed_in_mode"),
        scenario_params.get("k_push_cent"),
        scenario_params.get("monthly_fixed_feed_in_rates"),
    )


def hardware_reference_fingerprint(scenario_params: dict | None) -> tuple:
    """Vergleichsschlüssel für Referenz-PV (Batterie spielt in Referenz-€ keine Rolle)."""
    if not scenario_params:
        return ()
    return (float(scenario_params.get("pv_kwp", 0.0) or 0.0),)


def reference_fingerprint(scenario_params: dict | None) -> tuple:
    """Tarif + PV für Zuordnung der Referenz-Spalte je Szenario."""
    return (
        tariff_reference_fingerprint(scenario_params),
        hardware_reference_fingerprint(scenario_params),
    )


def resolve_profile_spec_flex_targets(
    flex_consumers: list[dict],
    house_profile: dict,
    slot_datetimes: list[datetime],
    *,
    historical_totals: dict[str, float] | None = None,
    window_end: datetime | None = None,
    climate: ModeledClimateContext | None = None,
) -> dict[str, float]:
    """
    Flex-Zielenergie für profile_spec: Hausprofil-Generic + cons_data für reine Config-Verbraucher.
    """
    if not flex_consumers:
        return {}
    profile_ids = _house_profile_consumer_ids(house_profile)
    targets = planning_flex_daily_targets(
        flex_consumers,
        house_profile,
        slot_datetimes,
        window_end=window_end,
    )
    targets.update(
        planning_ev_daily_targets(
            flex_consumers,
            house_profile,
            slot_datetimes,
            window_end=window_end,
        )
    )
    targets.update(
        planning_thermal_daily_targets(
            flex_consumers,
            house_profile,
            slot_datetimes,
            climate=climate,
        )
    )
    targets.update(
        planning_thermal_rc_daily_targets(
            flex_consumers,
            house_profile,
            slot_datetimes,
            climate=climate,
        )
    )
    cons_totals = historical_totals or {}
    for consumer in flex_consumers:
        cid = consumer["id"]
        if cid in profile_ids or cid in targets:
            continue
        cons_kwh = float(cons_totals.get(cid, 0.0) or 0.0)
        if cid in cons_totals and cons_kwh > 0.0:
            targets[cid] = round(cons_kwh, 3)
        else:
            targets[cid] = round(float(consumer.get("daily_target_kwh", 0.0) or 0.0), 3)
    return targets


def _used_chart_color_indices(consumers: list[dict]) -> set[int]:
    used: set[int] = set()
    for consumer in consumers:
        raw = consumer.get("chart_color_index")
        if raw is None:
            continue
        try:
            used.add(int(raw))
        except (TypeError, ValueError):
            continue
    return used


# Historical Chart-1 / Sankey indices (Consumer colors P1): violet→…→orange palette.
# Used when config.json has no flexible_consumers row to overlay from.
_DEFAULT_CHART_COLOR_INDEX_BY_ID: dict[str, int] = {
    "swimspa": 0,
    "pool_filter": 1,
    "ev": 2,
    "wp_heating": 7,
}

# Prefer violet/blue/cyan/orange over mid-palette greens (indices 3–6) for auto-assign.
_CHART_COLOR_ALLOCATION_ORDER: tuple[int, ...] = (0, 1, 2, 7, 6, 3, 5, 4)


def _allocate_chart_color_index(used: set[int], consumer_id: str) -> int:
    preferred = _DEFAULT_CHART_COLOR_INDEX_BY_ID.get(str(consumer_id))
    if preferred is not None and preferred not in used:
        return preferred
    for index in _CHART_COLOR_ALLOCATION_ORDER:
        if index not in used:
            return index
    return sum(ord(char) for char in consumer_id) % CONSUMER_PALETTE_SIZE


def merge_flexible_consumers(
    base_consumers: list[dict],
    planning_consumers: list[dict],
) -> list[dict]:
    """Config-Verbraucher + Planungs-Verbraucher, zusammengeführt über die kanonische id."""
    merged_map: dict[str, dict] = {c["id"]: dict(c) for c in base_consumers}
    used_indices = _used_chart_color_indices(list(merged_map.values()))
    for consumer in planning_consumers:
        entry = dict(consumer)
        canonical_id = str(entry["id"])
        if canonical_id in merged_map:
            continue
        if entry.get("chart_color_index") is None:
            index = _allocate_chart_color_index(used_indices, canonical_id)
            entry["chart_color_index"] = index
            used_indices.add(index)
        merged_map[canonical_id] = entry
    return list(merged_map.values())
