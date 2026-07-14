"""Normalisierung flexibler Verbraucher aus config.json."""
from __future__ import annotations

from datetime import datetime

from settings.ev_power import merge_ev_power_conversion_fields

CONSUMER_PALETTE_SIZE = 8


def normalize_day_schedule(block: dict | None) -> dict:
    if not isinstance(block, dict):
        return {}
    out = {}
    available = block.get("car_available_from_hour", block.get("charge_from_hour"))
    ready = block.get("ready_by_hour", block.get("charge_until_hour"))
    if available is not None:
        out["car_available_from_hour"] = int(available) % 24
    if ready is not None:
        out["ready_by_hour"] = int(ready) % 24
    if block.get("daily_rest_soc") is not None:
        out["daily_rest_soc"] = float(block["daily_rest_soc"])
    return out


def charging_efficiency(sched: dict) -> float:
    """Lade-Wirkungsgrad (Netz-/Zählerenergie → Akku); Default 0,95 wenn nicht gesetzt."""
    raw = sched.get("charging_efficiency")
    if raw is None:
        return 0.90
    efficiency = float(raw)
    if efficiency <= 0.0 or efficiency > 1.0:
        raise ValueError(
            "charging_schedule.charging_efficiency muss ein Wert zwischen 0 (exklusiv) "
            "und 1 (inklusiv) sein."
        )
    return efficiency


def target_kwh_from_rest_soc(
    consumer: dict,
    rest_soc_percent: float | None,
    *,
    capacity_kwh: float | None,
) -> float | None:
    """Berechnet Ladeziel (kWh) aus Rest-SOC (%), Kapazität und Lade-Wirkungsgrad."""
    if rest_soc_percent is None:
        return None
    if capacity_kwh is None:
        return None
    capacity = float(capacity_kwh)
    if capacity <= 0:
        return None
    sched = consumer.get("charging_schedule") or {}
    target_soc = float(sched.get("target_soc_percent", 100.0) or 100.0)
    battery_delta_kwh = (target_soc - float(rest_soc_percent)) / 100.0 * capacity
    eff = charging_efficiency(sched)
    return max(0.0, battery_delta_kwh / eff)


def target_kwh_from_day_schedule(
    consumer: dict,
    when: datetime,
    *,
    capacity_kwh: float | None,
) -> float | None:
    """Ladeziel (kWh) aus daily_rest_soc des passenden Wochentags in charging_schedule."""
    sched = consumer.get("charging_schedule")
    if not sched or not sched.get("enabled"):
        return None
    day_key = "weekend" if when.weekday() >= 5 else "weekday"
    rest_soc = (sched.get(day_key) or {}).get("daily_rest_soc")
    return target_kwh_from_rest_soc(consumer, rest_soc, capacity_kwh=capacity_kwh)


def normalize_loxone_outputs(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    enable_name = str(raw.get("enable_name", "")).strip()
    setpoint_name = str(raw.get("power_setpoint_name", "")).strip()
    if enable_name and setpoint_name:
        raise ValueError(
            "Kritischer Konfigurationsfehler: enable_name und power_setpoint_name "
            "dürfen nicht gleichzeitig gesetzt sein."
        )
    out: dict[str, str] = {}
    if enable_name:
        out["enable_name"] = enable_name
    if setpoint_name:
        out["power_setpoint_name"] = setpoint_name
    pv_follow_name = str(raw.get("pv_follow_name", "")).strip()
    if pv_follow_name:
        if not setpoint_name:
            raise ValueError(
                "Kritischer Konfigurationsfehler: pv_follow_name erfordert "
                "power_setpoint_name."
            )
        out["pv_follow_name"] = pv_follow_name
    return out


def normalize_loxone_inputs(raw: dict | None) -> dict:
    """Live-Messwerte aus Loxone (cons_data / Monitoring)."""
    if not isinstance(raw, dict):
        return {}
    power_name = str(raw.get("power_name", "")).strip()
    if not power_name:
        return {}
    result: dict = {"power_name": power_name}
    signal_type = str(raw.get("signal_type", "")).strip().lower()
    if signal_type in ("power", "binary"):
        result["signal_type"] = signal_type
    alt_name = str(raw.get("alternate_binary_power_name", "")).strip()
    if alt_name:
        result["alternate_binary_power_name"] = alt_name
    subtract_ids = raw.get("subtract_consumer_ids")
    if isinstance(subtract_ids, list):
        cleaned = [str(item).strip() for item in subtract_ids if str(item).strip()]
        if cleaned:
            result["subtract_consumer_ids"] = cleaned
    return result


def normalize_filter_schedule(raw, consumer_id: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    enabled = bool(raw.get("enabled"))
    if not enabled:
        return {"enabled": False}
    loxone_raw = raw.get("loxone") if isinstance(raw.get("loxone"), dict) else {}
    fallback_raw = raw.get("config_fallback") if isinstance(raw.get("config_fallback"), dict) else {}
    return {
        "enabled": True,
        "loxone": {
            "native_start_hour_name": str(loxone_raw.get("native_start_hour_name", "")).strip(),
            "native_duration_hours_name": str(loxone_raw.get("native_duration_hours_name", "")).strip(),
        },
        "config_fallback": {
            "native_start_hour": fallback_raw.get("native_start_hour"),
            "native_duration_hours": fallback_raw.get("native_duration_hours"),
        },
    }


def normalize_charging_schedule(raw: dict | None) -> dict | None:
    if not raw or not bool(raw.get("enabled", False)):
        return None
    loxone = {}
    if isinstance(raw.get("loxone"), dict):
        for key in (
            "plugged_in_name",
            "ready_by_time_name",
            "soc_at_plug_in_name",
            "actual_soc_name",
            "nominal_power_kw_name",
            "battery_capacity_kwh_name",
            "charge_immediate_remaining_name",
            "charge_enable_name",
            "charge_immediate_name",
        ):
            if raw["loxone"].get(key):
                loxone[key] = str(raw["loxone"][key]).strip()
        loxone.update(merge_ev_power_conversion_fields({}, raw["loxone"]))
    if not loxone.get("battery_capacity_kwh_name"):
        raise ValueError(
            "Kritischer Konfigurationsfehler: charging_schedule.enabled=true "
            "erfordert loxone.battery_capacity_kwh_name (Kapazität nur aus Loxone)."
        )
    charging_efficiency_raw = raw.get("charging_efficiency")
    normalized_efficiency = (
        charging_efficiency({"charging_efficiency": charging_efficiency_raw})
        if charging_efficiency_raw is not None
        else 0.95
    )
    return merge_ev_power_conversion_fields(
        {
            "enabled": True,
            "forecast_when_absent": bool(raw.get("forecast_when_absent", False)),
            "target_soc_percent": float(raw.get("target_soc_percent", 100.0) or 100.0),
            "charging_efficiency": normalized_efficiency,
            "weekday": normalize_day_schedule(raw.get("weekday")),
            "weekend": normalize_day_schedule(raw.get("weekend")),
            "loxone": loxone,
        },
        raw,
    )


def normalize_thermal_control(raw: dict | None, consumer_id: str) -> dict | None:
    if not isinstance(raw, dict) or not bool(raw.get("enabled", False)):
        return None
    mode = str(raw.get("mode", "observe")).strip().lower()
    if mode not in ("observe", "active"):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            "thermal_control.mode muss 'observe' oder 'active' sein."
        )
    volume = raw.get("water_volume_liters")
    if volume is None:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            "thermal_control.water_volume_liters fehlt."
        )
    volume = float(volume)
    if volume <= 0:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            "thermal_control.water_volume_liters muss > 0 sein."
        )
    efficiency = raw.get("heating_efficiency")
    if efficiency is None:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            "thermal_control.heating_efficiency fehlt."
        )
    efficiency = float(efficiency)
    if not 0.0 < efficiency <= 1.0:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            "thermal_control.heating_efficiency muss zwischen 0 (exkl.) und 1 liegen."
        )
    heat_loss = raw.get("heat_loss_kw_per_k")
    if heat_loss is not None:
        heat_loss = float(heat_loss)
        if heat_loss < 0:
            raise ValueError(
                f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
                "thermal_control.heat_loss_kw_per_k muss >= 0 sein."
            )
    threshold = float(raw.get("heating_power_threshold_kw", 2.0) or 2.0)
    if threshold < 0:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            "thermal_control.heating_power_threshold_kw muss >= 0 sein."
        )
    step = float(raw.get("actual_temp_step_c", 0.5) or 0.5)
    if step <= 0:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            "thermal_control.actual_temp_step_c muss > 0 sein."
        )
    loxone = {}
    if isinstance(raw.get("loxone"), dict):
        for key in (
            "actual_temp_name",
            "setpoint_temp_name",
            "ambient_temp_name",
            "tolerance_c_name",
            "heating_active_name",
        ):
            if raw["loxone"].get(key):
                loxone[key] = str(raw["loxone"][key]).strip()
    history_logs = {}
    if isinstance(raw.get("history_logs"), dict):
        for key in (
            "actual_temp_csv",
            "ambient_temp_csv",
            "power_csv",
            "heating_active_csv",
            "filter_active_csv",
        ):
            path = str(raw["history_logs"].get(key, "")).strip()
            if path:
                history_logs[key] = path
    setpoint = raw.get("setpoint_c")
    tolerance = raw.get("tolerance_c")
    return {
        "enabled": True,
        "mode": mode,
        "setpoint_c": None if setpoint is None else float(setpoint),
        "tolerance_c": None if tolerance is None else float(tolerance),
        "water_volume_liters": volume,
        "heat_loss_kw_per_k": heat_loss,
        "heating_efficiency": efficiency,
        "heating_power_threshold_kw": threshold,
        "actual_temp_step_c": step,
        "history_logs": history_logs,
        "loxone": loxone,
    }


def normalize_chart_color_index(raw: dict, consumer_id: str) -> int:
    if "chart_color_index" not in raw:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            f"chart_color_index fehlt (Pflichtfeld, Integer 0–{CONSUMER_PALETTE_SIZE - 1})."
        )
    try:
        index = int(raw["chart_color_index"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            f"chart_color_index muss Integer 0–{CONSUMER_PALETTE_SIZE - 1} sein."
        ) from exc
    if index < 0 or index >= CONSUMER_PALETTE_SIZE:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            f"chart_color_index muss 0–{CONSUMER_PALETTE_SIZE - 1} sein, erhalten: {index}."
        )
    if "chart_color" in raw:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers '{consumer_id}' "
            "chart_color ist entfernt — nur chart_color_index verwenden."
        )
    return index


def normalize_consumer(raw: dict) -> dict:
    source = str(raw.get("daily_target_source", "config")).lower().strip()
    if "daily_target_source" not in raw:
        charging_raw = raw.get("charging_schedule")
        if isinstance(charging_raw, dict) and charging_raw.get("source"):
            legacy = str(charging_raw["source"]).lower().strip()
            if legacy in ("config", "historical", "loxone", "loxone_remaining_hours", "thermal"):
                source = legacy
    if source not in ("config", "historical", "loxone", "loxone_remaining_hours", "thermal"):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers Eintrag '{raw.get('id', '?')}' "
            "daily_target_source muss config, historical, loxone, loxone_remaining_hours oder thermal sein."
        )
    consumer_id = str(raw["id"])
    thermal_control = normalize_thermal_control(raw.get("thermal_control"), consumer_id)
    if source == "thermal":
        if not thermal_control or not thermal_control.get("enabled"):
            raise ValueError(
                f"Kritischer Konfigurationsfehler: '{consumer_id}' "
                "daily_target_source=thermal erfordert thermal_control.enabled=true."
            )
        if thermal_control.get("mode") != "active":
            raise ValueError(
                f"Kritischer Konfigurationsfehler: '{consumer_id}' "
                "daily_target_source=thermal erfordert thermal_control.mode=active."
            )
        if thermal_control.get("heat_loss_kw_per_k") is None:
            raise ValueError(
                f"Kritischer Konfigurationsfehler: '{consumer_id}' "
                "daily_target_source=thermal erfordert heat_loss_kw_per_k "
                "(python -m scripts.tune_thermal_model)."
            )
    loxone_outputs = normalize_loxone_outputs(raw.get("loxone_outputs"))
    charging_schedule = normalize_charging_schedule(raw.get("charging_schedule"))
    if not loxone_outputs and charging_schedule:
        sched_lox = charging_schedule.get("loxone") or {}
        if sched_lox.get("charge_enable_name"):
            loxone_outputs = {"enable_name": sched_lox["charge_enable_name"]}
    consumer_id = str(raw["id"])
    min_power_kw = None
    if "min_power_kw" in raw:
        min_power_kw = float(raw["min_power_kw"])
    if loxone_outputs.get("power_setpoint_name") and min_power_kw is None:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: flexible_consumers Eintrag '{consumer_id}' "
            "benötigt min_power_kw bei power_setpoint_name."
        )
    return {
        "id": consumer_id,
        "name": str(raw.get("name", raw["id"])),
        "chart_color_index": normalize_chart_color_index(raw, consumer_id),
        "nominal_power_kw": float(raw.get("nominal_power_kw", 0.0)),
        "min_power_kw": min_power_kw,
        "daily_target_kwh": float(raw.get("daily_target_kwh", 0.0)),
        "daily_target_source": source,
        "loxone_target_kwh_name": str(raw.get("loxone_target_kwh_name", "")).strip(),
        "loxone_target_hours_name": str(raw.get("loxone_target_hours_name", "")).strip(),
        "min_on_quarterhours": max(1, int(raw.get("min_on_quarterhours", raw.get("min_on_hours", 1) * 4))),
        "path_log": str(raw.get("path_log", "")),
        "signal_type": str(raw.get("signal_type", "power")),
        "log_signal_type": str(
            raw.get("log_signal_type") or raw.get("signal_type", "power")
        ),
        "optimizer_enabled": bool(raw.get("optimizer_enabled", True)),
        "loxone_outputs": loxone_outputs,
        "loxone_inputs": normalize_loxone_inputs(raw.get("loxone_inputs")),
        "charging_schedule": charging_schedule,
        "thermal_control": thermal_control,
        "filter_schedule": normalize_filter_schedule(raw.get("filter_schedule"), consumer_id),
    }


def consumer_has_daily_target(consumer: dict) -> bool:
    sched = consumer.get("charging_schedule")
    target_source = consumer.get("daily_target_source", "config")
    if sched and sched.get("enabled"):
        if target_source == "historical":
            return bool(consumer.get("path_log"))
        if target_source == "loxone":
            return True
        capacity = float(sched.get("battery_capacity_kwh", 0.0) or 0.0)
        if capacity > 0:
            for day_key in ("weekday", "weekend"):
                if (sched.get(day_key) or {}).get("daily_rest_soc") is not None:
                    return True
    if target_source in ("historical", "loxone", "loxone_remaining_hours", "thermal"):
        return True
    return float(consumer.get("daily_target_kwh", 0.0) or 0.0) > 0


def consumer_by_id(raw_config: dict, consumer_id: str) -> dict | None:
    for raw in raw_config.get("flexible_consumers", []):
        if raw.get("id") == consumer_id:
            return normalize_consumer(raw)
    return None


def consumer_path(raw_config: dict, consumer_id: str, default: str = "") -> str:
    consumer = consumer_by_id(raw_config, consumer_id)
    return consumer.get("path_log", default) if consumer else default
