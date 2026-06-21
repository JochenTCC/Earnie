# optimizer.py
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta, time
import json
import os
import pulp
import config
import loxone_client
import optimization_schedule
from file_metadata import (
    CONSUMER_STATE_SCHEMA,
    read_schema_version,
    stamp_payload,
    strip_metadata,
)


CONSUMER_STATE_FILE = "flexible_consumers_state.json"
_RESERVED_KW_COLUMNS = {
    "PV-Prognose (kW)",
    "Verbrauch-Prognose (kW)",
    "Geplante Batterie-Aktion (kW)",
    "Netzbezug (kW)",
}


def _clamp_power(value: float, max_power: float) -> float:
    return max(-max_power, min(value, max_power))


MODE_AUTOMATIK = 0
MODE_ZWANGS_LADEN = 1
MODE_ENTLADESPERRE = 2
MODE_ZWANGS_ENTLADEN = 3
_SOC_DELTA_THRESHOLD = 0.05


def _power_threshold_kw(max_power_kw: float) -> float:
    """Mindestleistung (kW) aus relativem Schwellenwert und max. Batterieleistung."""
    return max_power_kw * config.get_threshold_power()


def steuerbefehl_for_mode(mode: int, target_power_kw: float = 0.0) -> str:
    """Steuerbefehl-Text für Chart und Simulations-Tabelle."""
    if mode == MODE_ZWANGS_LADEN:
        return f"Zwangsladen ({target_power_kw} kW)"
    if mode == MODE_ENTLADESPERRE:
        return "Entladesperre aktiv"
    if mode == MODE_ZWANGS_ENTLADEN:
        return f"Zwangsentladen ({target_power_kw} kW)"
    return "Automatikbetrieb"


def battery_plan_kw_from_control(
    mode: int,
    target_power_kw: float,
    p_pv: float,
    p_con: float,
    total_flex_power: float,
    max_power_kw: float,
) -> float:
    """Batterieplan für run_state – abgeleitet aus Steuermodus (Huawei-Logik vereinfacht)."""
    net_pv_surplus = p_pv - p_con - total_flex_power
    if mode == MODE_ZWANGS_LADEN:
        return round(_clamp_power(target_power_kw, max_power_kw), 3)
    if mode == MODE_ZWANGS_ENTLADEN:
        return round(-_clamp_power(target_power_kw, max_power_kw), 3)
    if mode == MODE_ENTLADESPERRE:
        if net_pv_surplus > _power_threshold_kw(max_power_kw):
            return round(_clamp_power(net_pv_surplus, max_power_kw), 3)
        return 0.0
    return round(_clamp_power(net_pv_surplus, max_power_kw), 3)


def _automatik_discharge_kw(net_pv_surplus: float, max_power_kw: float) -> float:
    """Entladeleistung (kW, positiv) im Automatikmodus bei Lastdefizit ohne PV-Überschuss."""
    if net_pv_surplus >= -_power_threshold_kw(max_power_kw):
        return 0.0
    return round(min(-net_pv_surplus, max_power_kw), 3)


def overlay_main_run_on_rows(rows: list[dict], main_state: dict | None) -> list[dict]:
    """Ersetzt Stunde 0 durch den Produktiv-Durchlauf von main.py."""
    if not rows or not main_state or not main_state.get("success"):
        return rows
    updated = [dict(row) for row in rows]
    row = updated[0]
    mode = int(main_state.get("mode", MODE_AUTOMATIK))
    target_power = float(main_state.get("target_power_kw", 0.0) or 0.0)
    row["Steuerbefehl"] = steuerbefehl_for_mode(mode, target_power)
    if "battery_plan_kw" in main_state:
        row["Geplante Batterie-Aktion (kW)"] = float(main_state["battery_plan_kw"])
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = _consumer_column_name(consumer)
        if col in row:
            cid = consumer["id"]
            row[col] = float((main_state.get("consumer_powers_kw") or {}).get(cid, 0.0) or 0.0)
    row["Netzbezug (kW)"] = round(
        float(row["Verbrauch-Prognose (kW)"])
        + _flexible_consumer_power_kw(row)
        - float(row["PV-Prognose (kW)"])
        + float(row["Geplante Batterie-Aktion (kW)"]),
        2,
    )
    updated[0] = row
    return updated


def _apply_soc_change(
    old_soc: float,
    batt_action: float,
    battery_capacity_kwh: float,
    efficiency: float,
    min_soc_limit: float,
    max_soc_limit: float,
) -> tuple[float, float]:
    if batt_action >= 0:
        energy_change = batt_action * efficiency
    else:
        energy_change = batt_action / efficiency
    soc_change = (energy_change / battery_capacity_kwh) * 100
    new_soc = old_soc + soc_change
    if new_soc > max_soc_limit:
        new_soc = max_soc_limit
        actual_energy = ((max_soc_limit - old_soc) / 100) * battery_capacity_kwh
        batt_action = actual_energy / efficiency if actual_energy >= 0 else actual_energy * efficiency
    elif new_soc < min_soc_limit:
        new_soc = min_soc_limit
        actual_energy = ((min_soc_limit - old_soc) / 100) * battery_capacity_kwh
        batt_action = actual_energy * efficiency if actual_energy < 0 else actual_energy / efficiency
    return new_soc, batt_action


def _charge_kw_for_hourly_soc(
    current_soc: float,
    planned_soc: float,
    battery_capacity_kwh: float,
    efficiency: float,
    max_power_kw: float,
    min_soc: float,
    max_soc: float,
) -> float:
    """Ladeleistung (kW) für geplanten SoC nach 1 h (konsistent zu _apply_soc_change)."""
    planned = max(min_soc, min(max_soc, planned_soc))
    delta_soc = planned - current_soc
    if delta_soc <= _SOC_DELTA_THRESHOLD:
        return 0.0
    energy_kwh = (delta_soc / 100.0) * battery_capacity_kwh
    return round(_clamp_power(energy_kwh / efficiency, max_power_kw), 3)


def _discharge_kw_for_hourly_soc(
    current_soc: float,
    planned_soc: float,
    battery_capacity_kwh: float,
    efficiency: float,
    max_power_kw: float,
    min_soc: float,
    max_soc: float,
) -> float:
    """Entladeleistung (kW, positiv) für geplanten SoC nach 1 h (konsistent zu _apply_soc_change)."""
    planned = max(min_soc, min(max_soc, planned_soc))
    delta_soc = current_soc - planned
    if delta_soc <= _SOC_DELTA_THRESHOLD:
        return 0.0
    energy_kwh = (delta_soc / 100.0) * battery_capacity_kwh
    return round(_clamp_power(energy_kwh * efficiency, max_power_kw), 3)


def _day_indices(matrix: List[Dict[str, Any]], horizon: int) -> list[int]:
    """Stunden im Planungshorizont, die zum selben Kalendertag wie t=0 gehören."""
    ref_date = matrix[0].get("date")
    if ref_date is None:
        return list(range(horizon))
    return [t for t in range(horizon) if matrix[t].get("date") == ref_date]


def _matrix_slot_datetime(matrix: list, index: int) -> datetime:
    """Ermittelt den Zeitpunkt einer Matrix-Stunde."""
    row = matrix[index]
    slot = row.get("slot_datetime")
    if isinstance(slot, datetime):
        return slot.replace(minute=0, second=0, microsecond=0)
    row_date = row.get("date")
    hour = int(row.get("hour", 0)) % 24
    if row_date is not None:
        if isinstance(row_date, datetime):
            row_date = row_date.date()
        return datetime.combine(row_date, time(hour=hour))
    return datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)


def _matrix_charging_anchor(matrix: list) -> datetime | None:
    """Expliziter Abfahrt-/Fertig-Zeitpunkt (Backtesting-Fenster-Ende), falls gesetzt."""
    if not matrix:
        return None
    anchor = matrix[0].get("charging_anchor")
    if isinstance(anchor, datetime):
        return anchor.replace(minute=0, second=0, microsecond=0)
    return None


def _charging_schedule_enabled(consumer: dict) -> bool:
    sched = consumer.get("charging_schedule")
    return bool(sched and sched.get("enabled"))


def _schedule_day_key(dt: datetime) -> str:
    return "weekend" if dt.weekday() >= 5 else "weekday"


def _config_day_schedule(consumer: dict, dt: datetime) -> dict:
    sched = consumer.get("charging_schedule") or {}
    return sched.get(_schedule_day_key(dt), {}) or {}


def _parse_loxone_time_hm(text: str) -> time | None:
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(text.strip(), fmt)
            return parsed.time().replace(second=0, microsecond=0)
        except ValueError:
            continue
    return None


_LOXONE_WEEKDAY_NAMES = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
}


def _parse_loxone_relative_ready_by(text: str, from_dt: datetime) -> datetime | None:
    """Parst Loxone-Relative wie 'Heute, 23:30', 'Morgen, 06:00', 'Montag, 12:30'."""
    if ", " not in text:
        return None
    label, time_part = text.split(", ", 1)
    label = label.strip().lower()
    clock = _parse_loxone_time_hm(time_part)
    if clock is None:
        return None

    if label == "heute":
        candidate = datetime.combine(from_dt.date(), clock)
        if candidate <= from_dt:
            candidate += timedelta(days=1)
        return candidate

    if label == "morgen":
        return datetime.combine(from_dt.date() + timedelta(days=1), clock)

    target_weekday = _LOXONE_WEEKDAY_NAMES.get(label)
    if target_weekday is not None:
        for offset in range(8):
            day = from_dt.date() + timedelta(days=offset)
            if day.weekday() != target_weekday:
                continue
            candidate = datetime.combine(day, clock)
            if candidate > from_dt:
                return candidate
        return None

    return None


def _parse_loxone_ready_by_time(value: str | float | None, from_dt: datetime) -> datetime | None:
    """Wandelt einen Loxone-Zeitwert (relativ/absolut oder Legacy-Zahl) in eine Deadline um."""
    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        relative = _parse_loxone_relative_ready_by(text, from_dt)
        if relative is not None:
            return relative

        # Absolutes Datum, ggf. mit kurzem Wochentags-Prefix: "Sa, 20.06.2026 07:00"
        parse_text = text
        if ", " in text:
            prefix, remainder = text.split(", ", 1)
            if prefix.strip().lower() not in _LOXONE_WEEKDAY_NAMES and prefix.strip().lower() not in ("heute", "morgen"):
                if len(prefix) <= 3 and remainder.strip():
                    parse_text = remainder.strip()
        for fmt in (
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ):
            try:
                return datetime.strptime(parse_text, fmt).replace(second=0, microsecond=0)
            except ValueError:
                continue
        return None

    v = float(value)
    if 0 <= v < 24:
        hour = int(v)
        minute = int(round((v - hour) * 60)) % 60
    elif 0 <= v < 2400 and abs(v - int(v)) < 1e-6:
        hour = int(v) // 100
        minute = int(v) % 100
    elif v > 1_000_000_000:
        return datetime.fromtimestamp(v).replace(second=0, microsecond=0)
    else:
        return None
    hour %= 24
    minute %= 60
    candidate = from_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= from_dt:
        candidate += timedelta(days=1)
    if candidate > from_dt + timedelta(hours=24):
        return None
    return candidate


def _deadline_from_ready_hour(horizon_start: datetime, ready_hour: int | None) -> datetime | None:
    if ready_hour is None:
        return None
    ready_h = int(ready_hour) % 24
    for offset in range(8):
        day = horizon_start.date() + timedelta(days=offset)
        deadline = datetime.combine(day, time(hour=ready_h))
        if deadline > horizon_start:
            return deadline
    return None


def _fetch_loxone_charging_context(consumer: dict, horizon_start: datetime) -> dict:
    sched = consumer.get("charging_schedule") or {}
    lox = sched.get("loxone", {})
    plugged_val = (
        loxone_client.fetch_loxone_generic_value(lox.get("plugged_in_name", ""))
        if lox.get("plugged_in_name")
        else None
    )
    plugged_in = plugged_val is not None and int(round(float(plugged_val))) == 1
    if not plugged_in:
        return {
            "active": False,
            "deadline": None,
            "target_kwh": 0.0,
            "use_time_window": False,
            "source_label": "loxone (nicht angeschlossen)",
        }
    ready_raw = (
        loxone_client.fetch_loxone_raw_value(lox.get("ready_by_time_name", ""))
        if lox.get("ready_by_time_name")
        else None
    )
    deadline = _parse_loxone_ready_by_time(ready_raw, horizon_start)
    soc_val = (
        loxone_client.fetch_loxone_generic_value(lox.get("soc_at_plug_in_name", ""))
        if lox.get("soc_at_plug_in_name")
        else None
    )
    target_kwh = config.Config.target_kwh_from_rest_soc(consumer, soc_val)
    return {
        "active": True,
        "deadline": deadline,
        "target_kwh": round(target_kwh, 3) if target_kwh is not None else None,
        "use_time_window": False,
        "source_label": "loxone (angeschlossen, SOC → kWh)",
    }


def _historical_charging_context(
    consumer: dict,
    matrix: list,
    consumer_daily_targets_kwh: dict | None,
    horizon_start: datetime,
    *,
    realtime: bool,
) -> dict:
    charging_anchor = _matrix_charging_anchor(matrix)
    schedule_ref = charging_anchor or horizon_start
    day_sched = _config_day_schedule(consumer, schedule_ref)
    targets = resolve_horizon_consumer_targets_kwh(matrix, consumer_daily_targets_kwh)
    target_kwh = float(targets.get(consumer["id"], 0.0))
    if charging_anchor is not None:
        deadline = charging_anchor
    else:
        deadline = _deadline_from_ready_hour(horizon_start, day_sched.get("ready_by_hour"))
    if realtime:
        source_label = "historical (Profil 24h-Horizont + Config-Zeitfenster)"
    else:
        source_label = "historisch (Config-Zeitfenster + Log-Ziel)"
    return {
        "active": target_kwh > 0,
        "deadline": deadline,
        "target_kwh": round(target_kwh, 3) if target_kwh > 0 else 0.0,
        "use_time_window": True,
        "config_day_schedule": day_sched,
        "source_label": source_label,
    }


def _resolve_charging_context(
    consumer: dict,
    matrix: list,
    consumer_daily_targets_kwh: dict | None,
    logged_simulation: bool,
) -> dict:
    sched = consumer.get("charging_schedule")
    if not sched or not sched.get("enabled"):
        return {"active": True, "deadline": None, "target_kwh": None, "use_time_window": False}
    horizon_start = _matrix_slot_datetime(matrix, 0)
    target_source = consumer.get("daily_target_source", "config")
    if logged_simulation or target_source == "historical":
        return _historical_charging_context(
            consumer,
            matrix,
            consumer_daily_targets_kwh,
            horizon_start,
            realtime=not logged_simulation,
        )
    if target_source == "loxone":
        return _fetch_loxone_charging_context(consumer, horizon_start)
    day_sched = _config_day_schedule(consumer, horizon_start)
    rest_soc = day_sched.get("daily_rest_soc")
    target_kwh = config.Config.target_kwh_from_rest_soc(consumer, rest_soc)
    return {
        "active": True,
        "deadline": _deadline_from_ready_hour(horizon_start, day_sched.get("ready_by_hour")),
        "target_kwh": round(target_kwh, 3) if target_kwh is not None else None,
        "use_time_window": True,
        "config_day_schedule": day_sched,
        "source_label": "config.json (daily_rest_soc → kWh)",
    }


def resolve_charging_contexts(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
) -> dict[str, dict]:
    """Ladekontext je Verbraucher mit charging_schedule für den Optimierungshorizont."""
    logged_simulation = bool(
        optimization_matrix
        and optimization_matrix[0].get("consumption_mode") == "logged_day"
    )
    contexts: dict[str, dict] = {}
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        if not _charging_schedule_enabled(consumer):
            continue
        contexts[consumer["id"]] = _resolve_charging_context(
            consumer,
            optimization_matrix,
            consumer_daily_targets_kwh,
            logged_simulation,
        )
    return contexts


def _apply_horizon_charging_limits(
    horizon_limits: dict[str, float],
    charging_contexts: dict[str, dict],
) -> dict[str, float]:
    adjusted = dict(horizon_limits)
    for cid, ctx in charging_contexts.items():
        if not ctx.get("active", True):
            adjusted[cid] = 0.0
        elif ctx.get("target_kwh") is not None:
            adjusted[cid] = round(float(ctx["target_kwh"]), 3)
    return adjusted


def _hour_in_charging_window(hour: int, available_from_h: int, ready_by_h: int) -> bool:
    """Prüft Ladezeitfenster: ab car_available_from_hour bis ready_by_hour (exklusiv, Mitternacht-Sprung)."""
    available_from_h %= 24
    ready_by_h %= 24
    if available_from_h == ready_by_h:
        return True
    if available_from_h < ready_by_h:
        return available_from_h <= hour < ready_by_h
    return hour >= available_from_h or hour < ready_by_h


def _consumer_charging_eligible_indices(
    matrix: list,
    consumer: dict,
    schedule_indices: list[int],
    charging_context: dict | None = None,
) -> list[int]:
    """Stunden im Horizont, in denen der Verbraucher laden darf (vor Deadline / im Zeitfenster)."""
    if not schedule_indices:
        return []
    if charging_context is not None and not charging_context.get("active", True):
        return []
    if charging_context is None and not _charging_schedule_enabled(consumer):
        return list(schedule_indices)
    ctx = charging_context or {}
    deadline = ctx.get("deadline")
    if deadline is None and _charging_schedule_enabled(consumer):
        horizon_start = _matrix_slot_datetime(matrix, 0)
        day_sched = ctx.get("config_day_schedule") or _config_day_schedule(consumer, horizon_start)
        deadline = _deadline_from_ready_hour(horizon_start, day_sched.get("ready_by_hour"))
    use_time_window = bool(ctx.get("use_time_window"))
    eligible = []
    for t in schedule_indices:
        slot_dt = _matrix_slot_datetime(matrix, t)
        if deadline is not None and slot_dt >= deadline:
            continue
        if not use_time_window:
            eligible.append(t)
            continue
        day_sched = ctx.get("config_day_schedule") or _config_day_schedule(consumer, slot_dt)
        from_h = day_sched.get("car_available_from_hour")
        until_h = day_sched.get("ready_by_hour")
        if from_h is None and until_h is None:
            eligible.append(t)
            continue
        from_h = int(from_h) if from_h is not None else 0
        until_h = int(until_h) if until_h is not None else 24
        if _hour_in_charging_window(slot_dt.hour, from_h, until_h):
            eligible.append(t)
    return eligible


def _apply_charging_window_constraints(
    prob,
    consumer_on: dict[str, list],
    matrix: list,
    consumer: dict,
    schedule_indices: list[int],
    charging_context: dict | None = None,
) -> list[int]:
    """Setzt MILP-Nebenbedingungen für Ladezeitfenster; liefert die zulässigen Stunden."""
    cid = consumer["id"]
    eligible = _consumer_charging_eligible_indices(
        matrix, consumer, schedule_indices, charging_context
    )
    blocked = set(schedule_indices) - set(eligible)
    for t in blocked:
        prob += consumer_on[cid][t] == 0
    return eligible


def _consumer_column_name(consumer: dict) -> str:
    return f"{consumer['name']} (kW)"


def _active_consumers(consumers: list | None = None) -> list:
    return consumers if consumers is not None else config.get_flexible_consumers(optimizer_only=True)


def _load_consumer_state() -> dict:
    today = datetime.now().date().isoformat()
    if not os.path.exists(CONSUMER_STATE_FILE):
        return {"date": today, "delivered": {}}
    try:
        with open(CONSUMER_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        schema_version = read_schema_version(state, default=1)
        if schema_version > CONSUMER_STATE_SCHEMA:
            import logging
            logging.getLogger(__name__).warning(
                "flexible_consumers_state: neuere Schema-Version %s (aktuell %s) – lese best effort",
                schema_version,
                CONSUMER_STATE_SCHEMA,
            )
        state = strip_metadata(state)
        if state.get("date") != today:
            return {"date": today, "delivered": {}}
        delivered = state.get("delivered", {})
        if not isinstance(delivered, dict):
            return {"date": today, "delivered": {}}
        return {"date": today, "delivered": delivered}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {"date": today, "delivered": {}}


def _save_consumer_state(state: dict) -> None:
    payload = stamp_payload(strip_metadata(state), schema_version=CONSUMER_STATE_SCHEMA)
    with open(CONSUMER_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def get_consumer_remaining_kwh(
    consumers: list | None = None,
    optimization_matrix: list | None = None,
    consumer_daily_targets_kwh: dict | None = None,
) -> dict[str, float]:
    """Verbleibende Zielenergie aller optimierbaren Verbraucher (inkl. Loxone E-Auto)."""
    import consumer_targets
    active = _active_consumers(consumers)
    state = _load_consumer_state()
    delivered = state.get("delivered", {})
    if optimization_matrix is not None:
        daily_targets = resolve_horizon_consumer_targets_kwh(
            optimization_matrix, consumer_daily_targets_kwh
        )
        charging_contexts = resolve_charging_contexts(
            optimization_matrix, consumer_daily_targets_kwh
        )
        daily_targets = _apply_horizon_charging_limits(daily_targets, charging_contexts)
    else:
        daily_targets = consumer_targets.resolve_consumer_daily_targets()
    remaining = {}
    for consumer in active:
        cid = consumer["id"]
        daily_target = float(daily_targets.get(cid, consumer["daily_target_kwh"]))
        already = float(delivered.get(cid, 0.0))
        remaining[cid] = max(0.0, daily_target - already)
    return remaining


def _optimization_interval_hours() -> float:
    """Dauer eines Live-Optimierungszyklus in Stunden (Viertelstunde)."""
    return optimization_schedule.optimization_interval_hours()


def register_consumer_hours(consumer_powers: dict[str, float]) -> None:
    """Bucht die gelieferte Energie aller Verbraucher im aktuellen Optimierungsintervall."""
    if not consumer_powers:
        return
    interval_h = _optimization_interval_hours()
    state = _load_consumer_state()
    delivered = dict(state.get("delivered", {}))
    for cid, power_kw in consumer_powers.items():
        if power_kw > 0:
            delivered[cid] = round(float(delivered.get(cid, 0.0)) + power_kw * interval_h, 3)
    state["delivered"] = delivered
    _save_consumer_state(state)


def get_spa_remaining_kwh() -> float:
    """Legacy: verbleibendes SwimSpa-Tagesziel."""
    return get_consumer_remaining_kwh().get("swimspa", 0.0)


def register_spa_hour(spa_power_kw: float) -> None:
    """Legacy: SwimSpa-Stunde buchen."""
    if spa_power_kw > 0:
        register_consumer_hours({"swimspa": spa_power_kw})


def _min_delivery_kwh(consumer: dict) -> float:
    """Mindest-Energie (kWh) für eine einzelne Einschaltperiode (min_on_quarterhours)."""
    min_hours = max(1, (int(consumer["min_on_quarterhours"]) + 3) // 4)
    return consumer["nominal_power_kw"] * min_hours


def _max_delivery_cap_kwh(consumer: dict, target: float, day_hours: int) -> float:
    """Obergrenze für Flex-Energie: Ziel plus höchstens eine Mindestperiode (min_on-Granularität)."""
    return _feasible_target_kwh(consumer, target, day_hours)


def _feasible_target_kwh(consumer: dict, target: float, day_hours: int) -> float:
    """Rundet das Ziel auf die kleinste mit min_on erreichbare Energiemenge (volle Stunden à Nennleistung)."""
    if target <= 0:
        return 0.0
    power = consumer["nominal_power_kw"]
    min_hours = max(1, (int(consumer["min_on_quarterhours"]) + 3) // 4)
    for hours in range(min_hours, day_hours + 1):
        if hours * power >= target - 1e-6:
            return hours * power
    return day_hours * power


_EMPTY_MILP_PLAN = {
    "p_grid_buy": 0.0,
    "p_grid_sell": 0.0,
    "p_charge": 0.0,
    "p_discharge": 0.0,
}


def _add_min_on_time_constraints(prob, on_vars: list, min_on_quarterhours: int, prefix: str) -> None:
    """Erzwingt Mindest-Einschaltdauer; MILP arbeitet stündlich (4 Viertelstunden = 1 Slot)."""
    min_hours = max(1, (int(min_on_quarterhours) + 3) // 4)
    if min_hours <= 1:
        return
    horizon = len(on_vars)
    for t in range(horizon - min_hours + 1):
        prev = 0 if t == 0 else on_vars[t - 1]
        prob += pulp.lpSum(on_vars[t:t + min_hours]) >= min_hours * (on_vars[t] - prev)


def _filter_feasible_consumers(
    consumers: list,
    remaining_kwh: dict[str, float],
    matrix: list,
    schedule_indices: list[int],
    verbose: bool,
    charging_contexts: dict[str, dict] | None = None,
) -> list:
    """Entfernt Verbraucher, deren Ziel im verbleibenden Horizont nicht erreichbar ist."""
    feasible = []
    charging_contexts = charging_contexts or {}
    for consumer in consumers:
        cid = consumer["id"]
        target = remaining_kwh.get(cid, 0.0)
        if target <= 0:
            continue
        ctx = charging_contexts.get(cid)
        if ctx is not None and not ctx.get("active", True):
            continue
        eligible = _consumer_charging_eligible_indices(
            matrix, consumer, schedule_indices, ctx
        )
        capacity_indices = eligible if eligible else schedule_indices
        max_deliverable = len(capacity_indices) * consumer["nominal_power_kw"]
        if target > max_deliverable + 1e-6:
            if verbose:
                sched_hint = ""
                if _charging_schedule_enabled(consumer):
                    sched_hint = f" ({len(eligible)} h im Ladezeitfenster)"
                print(
                    f"⚠️ {consumer['name']}: Ziel ({target:.2f} kWh) nicht erreichbar "
                    f"mit {len(capacity_indices)} h à {consumer['nominal_power_kw']:.2f} kW"
                    f"{sched_hint}. Wird übersprungen."
                )
            continue
        feasible.append(consumer)
    return feasible


def heuristic_optimizer(
    matrix: List[Dict[str, Any]],
    current_hour: int,
    current_soc: float,
    battery_params: dict | None = None,
    k_push: float | None = None,
    verbose: bool = True,
    consumers: list | None = None,
    consumer_remaining_kwh: dict[str, float] | None = None,
    spa_cfg: dict | None = None,
    spa_remaining_kwh: float | None = None,
    flex_indices: list[int] | None = None,
    charging_contexts: dict[str, dict] | None = None,
) -> Tuple[int, float, float, dict[str, float], dict[str, float]]:
    """
    Berechnet den optimalen Betriebsmodus und die Ziel-Leistung für den Loxone Miniserver.
    Optimiert Batterie und alle konfigurierten flexible_consumers gemeinsam per MILP.
    Rückgabe: (mode, target_power, target_soc, {consumer_id: leistung_kw}, milp_plan)
    """
    if not matrix:
        print("🚨 Optimizer-Fehler: Matrix ist leer.")
        return 0, 0.0, 99.0, {}, _EMPTY_MILP_PLAN
    battery_params = battery_params or config.get_battery_params()
    battery_capacity = battery_params["battery_capacity_kwh"]
    min_soc = battery_params["min_soc"]
    max_soc = battery_params["max_soc"]
    max_power = battery_params["max_power_kw"]
    efficiency = battery_params["efficiency"]
    k_push = k_push if k_push is not None else config.get_push_price_cent()
    active = _active_consumers(consumers)
    remaining: dict[str, float] = {}
    for consumer in active:
        cid = consumer["id"]
        if consumer_remaining_kwh and cid in consumer_remaining_kwh:
            remaining[cid] = max(0.0, float(consumer_remaining_kwh[cid]))
        else:
            remaining[cid] = float(consumer["daily_target_kwh"])
    # Legacy-Parameter für SwimSpa (Abwärtskompatibilität)
    if spa_remaining_kwh is not None and "swimspa" in remaining:
        remaining["swimspa"] = max(0.0, float(spa_remaining_kwh))
    N = min(24, len(matrix))
    e_min = (min_soc / 100.0) * battery_capacity
    e_max = (max_soc / 100.0) * battery_capacity
    e_init = (current_soc / 100.0) * battery_capacity
    day_indices = _day_indices(matrix, N)
    schedule_indices = flex_indices if flex_indices is not None else day_indices
    charging_contexts = charging_contexts or {}
    planned_consumers = _filter_feasible_consumers(
        active, remaining, matrix[:N], schedule_indices, verbose, charging_contexts
    )
    prob = pulp.LpProblem("Energy_Cost_Minimization", pulp.LpMinimize)
    p_grid_buy = [pulp.LpVariable(f"p_grid_buy_{t}", lowBound=0) for t in range(N)]
    p_grid_sell = [pulp.LpVariable(f"p_grid_sell_{t}", lowBound=0) for t in range(N)]
    p_charge = [pulp.LpVariable(f"p_charge_{t}", lowBound=0, upBound=max_power) for t in range(N)]
    p_discharge = [pulp.LpVariable(f"p_discharge_{t}", lowBound=0, upBound=max_power) for t in range(N)]
    e_batt = [pulp.LpVariable(f"e_batt_{t}", lowBound=e_min, upBound=e_max) for t in range(N)]
    delta_charge = [pulp.LpVariable(f"delta_charge_{t}", cat=pulp.LpBinary) for t in range(N)]
    max_flex_power = sum(c["nominal_power_kw"] for c in planned_consumers)
    max_load = max((row["expected_p_act"] for row in matrix[:N]), default=0.0)
    max_pv = max((row["expected_p_pv"] for row in matrix[:N]), default=0.0)
    big_m_grid = max(max_load + max_flex_power + max_power, max_pv + max_power, 50.0)
    delta_import = [pulp.LpVariable(f"delta_import_{t}", cat=pulp.LpBinary) for t in range(N)]
    consumer_on: dict[str, list] = {}
    for consumer in planned_consumers:
        cid = consumer["id"]
        consumer_on[cid] = [
            pulp.LpVariable(f"{cid}_on_{t}", cat=pulp.LpBinary)
            for t in range(N)
        ]
        _add_min_on_time_constraints(
            prob,
            consumer_on[cid],
            consumer["min_on_quarterhours"],
            cid,
        )
    prob += pulp.lpSum([
        p_grid_buy[t] * matrix[t]["k_act"] - p_grid_sell[t] * k_push
        for t in range(N)
    ])
    for t in range(N):
        p_pv = matrix[t]["expected_p_pv"]
        p_con = matrix[t]["expected_p_act"]
        p_flex = pulp.lpSum(
            consumer["nominal_power_kw"] * consumer_on[consumer["id"]][t]
            for consumer in planned_consumers
        )
        prob += (p_pv + p_grid_buy[t] + p_discharge[t] == p_con + p_flex + p_grid_sell[t] + p_charge[t])
        # Kein gleichzeitiger Netzbezug und Einspeisung (verhindert unbounded arbitrage)
        prob += (p_grid_buy[t] <= big_m_grid * delta_import[t])
        prob += (p_grid_sell[t] <= big_m_grid * (1 - delta_import[t]))
        prob += (p_charge[t] <= max_power * delta_charge[t])
        prob += (p_discharge[t] <= max_power * (1 - delta_charge[t]))
        if t == 0:
            prob += (e_batt[t] == e_init + p_charge[t] * efficiency - p_discharge[t] / efficiency)
        else:
            prob += (e_batt[t] == e_batt[t - 1] + p_charge[t] * efficiency - p_discharge[t] / efficiency)
    for consumer in planned_consumers:
        cid = consumer["id"]
        target = remaining.get(cid, 0.0)
        if target <= 0:
            continue
        eligible = _apply_charging_window_constraints(
            prob,
            consumer_on,
            matrix[:N],
            consumer,
            schedule_indices,
            charging_contexts.get(cid),
        )
        if not eligible:
            if verbose:
                print(
                    f"⚠️ {consumer['name']}: Kein zulässiges Ladezeitfenster im Horizont. "
                    "Flex-Laden wird übersprungen."
                )
            continue
        prob += (
            pulp.lpSum(
                consumer["nominal_power_kw"] * consumer_on[cid][t]
                for t in eligible
            ) >= target
        )
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[prob.status] != "Optimal":
        if verbose:
            print(
                f"⚠️ MILP-Solver konnte keine optimale Lösung finden "
                f"Status: {pulp.LpStatus[prob.status]}. Fallback auf Automatik."
            )
        return 0, 0.0, 99.0, {}, _EMPTY_MILP_PLAN
    opt_charge = p_charge[0].varValue if p_charge[0].varValue is not None else 0.0
    opt_discharge = p_discharge[0].varValue if p_discharge[0].varValue is not None else 0.0
    opt_grid_buy = p_grid_buy[0].varValue if p_grid_buy[0].varValue is not None else 0.0
    opt_grid_sell = p_grid_sell[0].varValue if p_grid_sell[0].varValue is not None else 0.0
    milp_plan = {
        "p_grid_buy": opt_grid_buy,
        "p_grid_sell": opt_grid_sell,
        "p_charge": opt_charge,
        "p_discharge": opt_discharge,
    }
    consumer_powers: dict[str, float] = {}
    total_flex_power = 0.0
    for consumer in planned_consumers:
        cid = consumer["id"]
        on_val = consumer_on[cid][0].varValue
        power = consumer["nominal_power_kw"] if on_val is not None and on_val > 0.5 else 0.0
        consumer_powers[cid] = power
        total_flex_power += power
    p_pv_0 = matrix[0]["expected_p_pv"]
    p_con_0 = matrix[0]["expected_p_act"]
    net_pv_surplus = p_pv_0 - p_con_0 - total_flex_power
    planned_soc = round(
        max(min_soc, min(max_soc, (e_batt[0].varValue / battery_capacity) * 100.0)),
        1,
    )
    mode = MODE_AUTOMATIK
    target_power = 0.0
    target_soc = 99.0
    if opt_charge > _power_threshold_kw(max_power) and opt_grid_buy > _power_threshold_kw(max_power):
        mode = MODE_ZWANGS_LADEN
        target_soc = round(max(current_soc, planned_soc), 1)
        target_power = _charge_kw_for_hourly_soc(
            current_soc,
            target_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
        )
    elif opt_discharge > _power_threshold_kw(max_power):
        candidate_soc = round(min(current_soc, planned_soc), 1)
        candidate_power = _discharge_kw_for_hourly_soc(
            current_soc,
            candidate_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
        )
        automatik_power = _automatik_discharge_kw(net_pv_surplus, max_power)
        if candidate_power > automatik_power + _power_threshold_kw(max_power):
            mode = MODE_ZWANGS_ENTLADEN
            target_soc = candidate_soc
            target_power = candidate_power
    elif (
        net_pv_surplus < -_power_threshold_kw(max_power)
        and opt_discharge < _power_threshold_kw(max_power)
        and current_soc > (min_soc + 2.0)
    ):
        mode = MODE_ENTLADESPERRE
        target_power = 0.0
        target_soc = 100.0
    if verbose:
        print(f"\n--- 🧮 MILP Optimierungs-Entscheidung für {current_hour}:00 Uhr ---")
        print(f"Aktueller Brutto-Preis: {matrix[0]['k_act']:.2f} Cent/kWh")
        print(f"Aktueller Akku-SoC    : {current_soc:.1f}%")
        print(
            f"Optimierter Fahrplan  : Ladung={opt_charge:.2f} kW | "
            f"Entladung={opt_discharge:.2f} kW | Netzbezug={opt_grid_buy:.2f} kW"
        )
        for consumer in planned_consumers:
            cid = consumer["id"]
            power_now = consumer_powers.get(cid, 0.0)
            planned_kwh = sum(
                consumer["nominal_power_kw"]
                for t in range(N)
                if consumer_on[cid][t].varValue is not None and consumer_on[cid][t].varValue > 0.5
            )
            print(
                f"{consumer['name']:<16}: Jetzt={'AN' if power_now > 0 else 'AUS'} "
                f"({power_now:.2f} kW) | Restziel={remaining.get(cid, 0.0):.2f} kWh | "
                f"Geplant={planned_kwh:.2f} kWh | min_on={consumer['min_on_quarterhours']} x 15min"
            )
        modi_text = {
            MODE_AUTOMATIK: "AUTOMATIK",
            MODE_ZWANGS_LADEN: "ZWANGSLADEN",
            MODE_ENTLADESPERRE: "ENTLADESPERRE",
            MODE_ZWANGS_ENTLADEN: "ZWANGSENTLADEN",
        }
        print(f"-> Steuerbefehl Loxone: {modi_text[mode]} (Leistung: {target_power} kW, Ziel-SoC: {target_soc}%)")
    return mode, target_power, target_soc, consumer_powers, milp_plan


def _resolve_daily_target_kwh(
    consumer: dict,
    consumer_daily_targets_kwh: dict | None,
    row_date=None,
    logged_targets_only: bool = False,
    ref_datetime: datetime | None = None,
    horizon_flex_kwh: float | None = None,
) -> float:
    """Tagesziel aus Overrides oder – je nach Modus – Logs bzw. daily_target_source."""
    cid = consumer["id"]
    if consumer_daily_targets_kwh is not None and logged_targets_only:
        if row_date is not None and row_date in consumer_daily_targets_kwh:
            day_targets = consumer_daily_targets_kwh[row_date]
            if isinstance(day_targets, dict) and cid in day_targets:
                return float(day_targets[cid])
        if cid in consumer_daily_targets_kwh:
            return float(consumer_daily_targets_kwh[cid])
    if logged_targets_only:
        import consumer_targets
        if row_date is None:
            return 0.0
        logged = consumer_targets.resolve_historical_consumer_daily_targets(row_date)
        return float(logged.get(cid, 0.0))
    if (
        consumer.get("daily_target_source", "config") == "historical"
        and horizon_flex_kwh is not None
    ):
        return float(horizon_flex_kwh)
    import consumer_targets
    day = row_date or datetime.now().date()
    when = ref_datetime or datetime.combine(day, time(12, 0))
    if (
        consumer.get("daily_target_source", "config") == "config"
        and consumer.get("charging_schedule", {}).get("enabled")
    ):
        computed = config.Config.target_kwh_from_day_schedule(consumer, when)
        if computed is not None:
            return float(computed)
    resolved = consumer_targets.resolve_consumer_daily_targets(target_date=day)
    return float(resolved.get(cid, consumer.get("daily_target_kwh", 0.0)))


def _resolve_horizon_target_kwh(
    consumer: dict,
    consumer_daily_targets_kwh: dict | None,
    row_date=None,
    logged_targets_only: bool = False,
    ref_datetime: datetime | None = None,
    horizon_flex_kwh: float | None = None,
) -> float:
    return _resolve_daily_target_kwh(
        consumer,
        consumer_daily_targets_kwh,
        row_date,
        logged_targets_only,
        ref_datetime=ref_datetime,
        horizon_flex_kwh=horizon_flex_kwh,
    )


def _is_flat_target_override(consumer_daily_targets_kwh: dict | None) -> bool:
    """True, wenn das Dict flache Verbraucher-IDs enthält (nicht {date: {id: kwh}})."""
    if not consumer_daily_targets_kwh:
        return False
    return not any(isinstance(v, dict) for v in consumer_daily_targets_kwh.values())


def resolve_horizon_consumer_targets_kwh(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
) -> dict[str, float]:
    """
    Flex-Zielenergie je Verbraucher für das gesamte 24h-Simulationsfenster (einmalig).
    Kein erneutes Zählen bei Kalendertagwechsel im rollierenden Horizont.
    """
    consumers_cfg = config.get_flexible_consumers(optimizer_only=True)
    if not optimization_matrix:
        return {c["id"]: 0.0 for c in consumers_cfg}
    logged_targets_only = (
        optimization_matrix[0].get("consumption_mode") == "logged_day"
    )
    ref_date = optimization_matrix[0].get("date")
    ref_dt = optimization_matrix[0].get("slot_datetime")
    if not isinstance(ref_dt, datetime):
        ref_dt = (
            datetime.combine(ref_date, time(12, 0))
            if ref_date is not None
            else datetime.now()
        )
    if _is_flat_target_override(consumer_daily_targets_kwh) and logged_targets_only:
        return {
            c["id"]: round(float(consumer_daily_targets_kwh.get(c["id"], 0.0)), 3)
            for c in consumers_cfg
        }
    horizon_flex_targets = None
    if not logged_targets_only:
        import consumer_targets
        horizon_flex_targets = consumer_targets.resolve_horizon_flex_targets_kwh(
            optimization_matrix
        )
    return {
        c["id"]: round(
            _resolve_horizon_target_kwh(
                c,
                consumer_daily_targets_kwh,
                ref_date,
                logged_targets_only,
                ref_datetime=ref_dt,
                horizon_flex_kwh=(
                    horizon_flex_targets.get(c["id"])
                    if horizon_flex_targets is not None
                    else None
                ),
            ),
            3,
        )
        for c in consumers_cfg
    }


def resolve_applied_daily_targets(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
) -> dict[str, float]:
    """Ermittelt die Tagesziele, die die Simulation tatsächlich verwendet."""
    return resolve_horizon_consumer_targets_kwh(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )


def build_applied_targets_detail(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
) -> list[dict]:
    """Bereitet die genutzten Tagesziele mit Verbrauchername und Quelle für die UI auf."""
    logged_day = bool(
        optimization_matrix
        and optimization_matrix[0].get("consumption_mode") == "logged_day"
    )
    targets = resolve_applied_daily_targets(optimization_matrix, consumer_daily_targets_kwh)
    charging_contexts = resolve_charging_contexts(optimization_matrix, consumer_daily_targets_kwh)
    targets = _apply_horizon_charging_limits(targets, charging_contexts)
    details = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        ctx = charging_contexts.get(cid)
        if ctx and ctx.get("source_label"):
            source = ctx["source_label"]
        elif logged_day:
            source = "geloggt (historischer Tag)"
        else:
            source_key = consumer.get("daily_target_source", "config")
            source_labels = {
                "config": "config.json (24h-Ziel)",
                "historical": "historical (24h-Ziel)",
                "loxone": "loxone (24h-Ziel)",
            }
            source = source_labels.get(source_key, f"{source_key} (24h-Ziel)")
        details.append({
            "id": cid,
            "name": consumer["name"],
            "target_kwh": round(float(targets.get(cid, 0.0)), 3),
            "source": source,
        })
    return details


def build_baseline_targets_detail(optimization_matrix: list) -> list[dict]:
    """
    Ermittelt die pro Verbraucher in der Baseline enthaltene Tagesenergie.
    Historisch: geloggte Summen im Gesamtverbrauchs-Stundenprofil.
    Echtzeit: Summe der stündlichen Flex-Profile (flexible_consumer_profiles.csv).
    """
    if not optimization_matrix:
        return []
    logged_day = optimization_matrix[0].get("consumption_mode") == "logged_day"
    consumers = config.get_flexible_consumers(optimizer_only=True)
    details = []
    if logged_day:
        row_date = optimization_matrix[0].get("date")
        import consumer_targets
        totals = consumer_targets.resolve_historical_consumer_daily_targets(row_date)
        source = "geloggt (Gesamtverbrauchs-Stundenprofil)"
        for consumer in consumers:
            cid = consumer["id"]
            details.append({
                "id": cid,
                "name": consumer["name"],
                "target_kwh": round(float(totals.get(cid, 0.0)), 3),
                "source": source,
            })
        return details
    flex_sums = {consumer["id"]: 0.0 for consumer in consumers}
    for row in optimization_matrix[:24]:
        flex = row.get("expected_flex_kw") or {}
        for cid in flex_sums:
            flex_sums[cid] += float(flex.get(cid, 0.0) or 0.0)
    has_profile_flex = any(v > 0 for v in flex_sums.values())
    source = (
        "Verbrauchsprofil (flexible_consumer_profiles.csv)"
        if has_profile_flex
        else "Gesamtprofil (total_consumption_profiles.csv, nicht aufgeteilt)"
    )
    for consumer in consumers:
        cid = consumer["id"]
        details.append({
            "id": cid,
            "name": consumer["name"],
            "target_kwh": round(flex_sums.get(cid, 0.0), 3),
            "source": source,
        })
    return details


def resolve_baseload_kwh(optimization_matrix: list) -> float:
    """Summiert die Grundlast (kWh) über den Simulationshorizont."""
    if not optimization_matrix:
        return 0.0
    return round(
        sum(float(row.get("expected_p_act", 0.0) or 0.0) for row in optimization_matrix[:24]),
        3,
    )


def build_energy_comparison_detail(
    optimization_matrix: list,
    consumer_daily_targets_kwh: dict | None = None,
) -> list[dict]:
    """Kombiniert Baseline-Verbrauch und Optimierungsziele je Verbraucher inkl. Grundlast."""
    baseload_kwh = resolve_baseload_kwh(optimization_matrix)
    logged_day = bool(
        optimization_matrix
        and optimization_matrix[0].get("consumption_mode") == "logged_day"
    )
    baseload_source = (
        "geloggt (historischer Tag)" if logged_day else "Verbrauchsprofil (consumption_profiles.csv)"
    )
    baseline_by_id = {
        item["id"]: item for item in build_baseline_targets_detail(optimization_matrix)
    }
    optimized_by_id = {
        item["id"]: item
        for item in build_applied_targets_detail(optimization_matrix, consumer_daily_targets_kwh)
    }
    rows = [{
        "name": "Grundlast",
        "baseline_kwh": baseload_kwh,
        "optimization_kwh": baseload_kwh,
        "optimization_source": baseload_source,
    }]
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        base = baseline_by_id.get(cid, {})
        opt = optimized_by_id.get(cid, {})
        rows.append({
            "name": consumer["name"],
            "baseline_kwh": base.get("target_kwh", 0.0),
            "optimization_kwh": opt.get("target_kwh", 0.0),
            "optimization_source": opt.get("source", ""),
        })
    return rows


def simulate_horizon(
    optimization_matrix: list,
    initial_soc: float,
    battery_params: dict | None = None,
    k_push: float | None = None,
    verbose: bool = True,
    on_progress=None,
    consumer_daily_targets_kwh: dict[str, float] | None = None,
) -> list:
    """Simuliert einen rollierenden Optimierungshorizont über die gesamte Matrix."""
    chart_rows = []
    sim_soc = initial_soc
    battery_params = battery_params or config.get_battery_params()
    total_steps = len(optimization_matrix)
    consumers_cfg = config.get_flexible_consumers(optimizer_only=True)
    horizon_limits = resolve_horizon_consumer_targets_kwh(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )
    charging_contexts = resolve_charging_contexts(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )
    horizon_limits = _apply_horizon_charging_limits(horizon_limits, charging_contexts)
    delivered_horizon: dict[str, float] = {c["id"]: 0.0 for c in consumers_cfg}
    for i, row in enumerate(optimization_matrix):
        remaining = {}
        for consumer in consumers_cfg:
            cid = consumer["id"]
            remaining[cid] = max(
                0.0,
                horizon_limits.get(cid, 0.0) - delivered_horizon.get(cid, 0.0),
            )
        remaining_slice = optimization_matrix[i:]
        sim_soc, chart_row, mode, target_power = _simulate_single_hour_optimizer(
            remaining_slice,
            row,
            sim_soc,
            battery_params,
            k_push=k_push,
            verbose=verbose,
            consumer_remaining_kwh=remaining,
            flex_indices=list(range(len(remaining_slice))),
            charging_contexts=charging_contexts,
        )
        flex_capped = False
        for consumer in consumers_cfg:
            col = _consumer_column_name(consumer)
            cid = consumer["id"]
            power = float(chart_row.get(col, 0.0) or 0.0)
            if power <= 0:
                continue
            max_kwh = horizon_limits.get(cid, 0.0)
            already = delivered_horizon.get(cid, 0.0)
            room = max(0.0, max_kwh - already)
            if power > room + 1e-6:
                power = room
                chart_row[col] = round(power, 2)
                flex_capped = True
            if power > 0:
                delivered_horizon[cid] = already + power
        if flex_capped:
            old_soc = float(chart_row["Simulierter SoC (%)"])
            sim_soc = _finalize_chart_row_energy(
                chart_row, mode, target_power, old_soc, battery_params
            )
        chart_rows.append(chart_row)
        if on_progress is not None:
            on_progress(i + 1, total_steps)
    return chart_rows


def simulate_24h_horizon(
    optimization_matrix: list,
    initial_soc: float,
    consumer_daily_targets_kwh: dict[str, float] | None = None,
    verbose: bool = True,
) -> list:
    """Simuliert den 24-Stunden-Verlauf des SoC."""
    return simulate_horizon(
        optimization_matrix[:24],
        initial_soc,
        consumer_daily_targets_kwh=consumer_daily_targets_kwh,
        verbose=verbose,
    )


def _simulate_single_hour_optimizer(
    remaining_matrix: list,
    row: dict,
    sim_soc: float,
    battery_params: dict,
    k_push: float | None = None,
    verbose: bool = True,
    consumer_remaining_kwh: dict[str, float] | None = None,
    spa_remaining_kwh: float | None = None,
    flex_indices: list[int] | None = None,
    charging_contexts: dict[str, dict] | None = None,
) -> Tuple[float, dict, int, float]:
    """Simuliert eine einzelne Stunde im optimierten Pfad (Huawei-Logik für die Batterie)."""
    h = row["hour"]
    mode, target_power, target_soc, consumer_powers, _ = heuristic_optimizer(
        remaining_matrix,
        h,
        sim_soc,
        battery_params=battery_params,
        k_push=k_push,
        verbose=verbose,
        consumer_remaining_kwh=consumer_remaining_kwh,
        spa_remaining_kwh=spa_remaining_kwh,
        flex_indices=flex_indices,
        charging_contexts=charging_contexts,
    )
    pv = row["expected_p_pv"]
    con = row["expected_p_act"]
    total_flex_power = sum(consumer_powers.values())
    max_power = battery_params["max_power_kw"]
    batt_action = battery_plan_kw_from_control(
        mode, target_power, pv, con, total_flex_power, max_power
    )
    action_text = steuerbefehl_for_mode(mode, target_power)
    old_soc = sim_soc
    sim_soc, batt_action = _apply_soc_change(
        old_soc,
        batt_action,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
    )
    p_grid = con + total_flex_power - pv + batt_action
    chart_row = {
        "Uhrzeit": f"{h:02d}:00",
        "Strompreis (Cent/kWh)": row["k_act"],
        "PV-Prognose (kW)": pv,
        "Verbrauch-Prognose (kW)": con,
        "Geplante Batterie-Aktion (kW)": round(batt_action, 2),
        "Netzbezug (kW)": round(p_grid, 2),
        "Simulierter SoC (%)": round(old_soc, 1),
        "Steuerbefehl": action_text,
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        chart_row[_consumer_column_name(consumer)] = round(
            consumer_powers.get(consumer["id"], 0.0), 2
        )
    return sim_soc, chart_row, mode, target_power


def _flexible_consumer_power_kw(row: dict) -> float:
    """Summiert alle flexiblen Verbraucher-Leistungen aus einer Chart-Zeile."""
    return sum(
        float(value or 0.0)
        for key, value in row.items()
        if key.endswith(" (kW)") and key not in _RESERVED_KW_COLUMNS
    )


def _finalize_chart_row_energy(
    chart_row: dict,
    mode: int,
    target_power: float,
    old_soc: float,
    battery_params: dict,
) -> float:
    """Leitet Batterieaktion, Netzbezug und End-SoC aus Zeileninhalt ab (Huawei-Logik)."""
    pv = float(chart_row["PV-Prognose (kW)"])
    con = float(chart_row["Verbrauch-Prognose (kW)"])
    total_flex = _flexible_consumer_power_kw(chart_row)
    max_power = battery_params["max_power_kw"]
    batt_action = battery_plan_kw_from_control(
        mode, target_power, pv, con, total_flex, max_power
    )
    new_soc, batt_action = _apply_soc_change(
        old_soc,
        batt_action,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
    )
    chart_row["Geplante Batterie-Aktion (kW)"] = round(batt_action, 2)
    chart_row["Netzbezug (kW)"] = round(con + total_flex - pv + batt_action, 2)
    return new_soc


def _total_consumption_kwh_from_rows(rows: list) -> float:
    """
    Summiert den Stundenverbrauch (Grundlast + flexible Verbraucher) über alle Zeilen.
    Jede Zeile = 1 Stunde; kW-Werte werden als kWh addiert.
    """
    return round(
        sum(
            float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
            + _flexible_consumer_power_kw(row)
            for row in rows
        ),
        3,
    )


def _delivered_flex_kwh_from_rows(rows: list) -> dict[str, float]:
    """Summiert die gelieferte Flex-Energie je Verbraucher über alle Simulationsstunden."""
    totals: dict[str, float] = {}
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = _consumer_column_name(consumer)
        totals[consumer["id"]] = round(
            sum(float(row.get(col, 0.0) or 0.0) for row in rows),
            3,
        )
    return totals


def _calculate_step_cost_euro_from_row(row: dict, sell_price_cent: float) -> float:
    """Berechnet die Stromkosten einer einzelnen Simulationsstunde in Euro."""
    p_con = row["Verbrauch-Prognose (kW)"] + _flexible_consumer_power_kw(row)
    price_cent = row["Strompreis (Cent/kWh)"]
    if "Netzbezug (kW)" in row:
        p_grid = float(row["Netzbezug (kW)"])
    else:
        p_pv = row["PV-Prognose (kW)"]
        batt_action = row["Geplante Batterie-Aktion (kW)"]
        p_grid = p_con - p_pv + batt_action
    if p_grid >= 0:
        step_cents = p_grid * price_cent
    else:
        step_cents = p_grid * sell_price_cent
    return step_cents / 100.0


def _calculate_cost_euro_from_rows(rows: list, sell_price_cent: float) -> float:
    """Berechnet die Kosten in Euro für eine Stundenreihe aus einem Simulations-Output."""
    return sum(_calculate_step_cost_euro_from_row(row, sell_price_cent) for row in rows)


def simulate_baseline_horizon(optimization_matrix: list, initial_soc: float) -> list:
    """Simuliert den 24h-Verlauf ohne Optimierung: Batterie folgt nur dem aktuellen PV-Überschuss."""
    chart_rows = []
    sim_soc = initial_soc
    battery_params = config.get_battery_params()
    for row in optimization_matrix[:24]:
        sim_soc, chart_row = _simulate_single_hour_baseline(row, sim_soc, battery_params)
        chart_rows.append(chart_row)
    return chart_rows


def _simulate_single_hour_baseline(row: dict, sim_soc: float, battery_params: dict) -> Tuple[float, dict]:
    """Simuliert eine einzelne Stunde im Baseline-Pfad."""
    h = row["hour"]
    pv = row["expected_p_pv"]
    flex_kw = row.get("expected_flex_kw") or {}
    has_flex_profile = any(float(v or 0.0) > 0.0 for v in flex_kw.values())
    logged_day = row.get("consumption_mode") == "logged_day"
    if logged_day and not has_flex_profile:
        con = float(row.get("expected_p_total", row["expected_p_act"]) or 0.0)
        total_flex_power = 0.0
        flex_kw = {}
    else:
        con = float(row["expected_p_act"] or 0.0)
        total_flex_power = sum(float(v or 0.0) for v in flex_kw.values())
    net_pv_surplus = pv - con - total_flex_power
    batt_action = _clamp_power(net_pv_surplus, battery_params["max_power_kw"])
    old_soc = sim_soc
    sim_soc, batt_action = _apply_soc_change(
        old_soc,
        batt_action,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
    )
    chart_row = {
        "Uhrzeit": f"{h:02d}:00",
        "Strompreis (Cent/kWh)": row["k_act"],
        "PV-Prognose (kW)": pv,
        "Verbrauch-Prognose (kW)": con,
        "Geplante Batterie-Aktion (kW)": round(batt_action, 2),
        "Simulierter SoC (%)": round(old_soc, 1),
        "Steuerbefehl": "Baseline",
    }
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        if flex_kw:
            chart_row[_consumer_column_name(consumer)] = round(
                float(flex_kw.get(consumer["id"], 0.0) or 0.0), 2
            )
    return sim_soc, chart_row


def calculate_optimization_savings(
    optimization_matrix: list,
    initial_soc: float,
    consumer_daily_targets_kwh: dict[str, float] | None = None,
) -> dict:
    """Berechnet die Einsparung in Euro gegenüber einer nicht-optimierten Baseline-Simulation."""
    optimized_rows = simulate_24h_horizon(
        optimization_matrix,
        initial_soc,
        consumer_daily_targets_kwh=consumer_daily_targets_kwh,
        verbose=False,
    )
    baseline_rows = simulate_baseline_horizon(optimization_matrix, initial_soc)
    sell_price_cent = config.get_push_price_cent()
    optimized_cost = _calculate_cost_euro_from_rows(optimized_rows, sell_price_cent)
    baseline_cost = _calculate_cost_euro_from_rows(baseline_rows, sell_price_cent)
    savings = baseline_cost - optimized_cost
    baseline_kwh = _total_consumption_kwh_from_rows(baseline_rows)
    optimized_kwh = _total_consumption_kwh_from_rows(optimized_rows)
    applied_targets = build_applied_targets_detail(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )
    baseline_targets = build_baseline_targets_detail(optimization_matrix)
    energy_comparison = build_energy_comparison_detail(
        optimization_matrix,
        consumer_daily_targets_kwh,
    )
    return {
        "baseline_cost_euro": round(baseline_cost, 4),
        "optimized_cost_euro": round(optimized_cost, 4),
        "savings_euro": round(savings, 4),
        "baseline_consumption_kwh": round(baseline_kwh, 3),
        "optimized_consumption_kwh": round(optimized_kwh, 3),
        "baseload_kwh": resolve_baseload_kwh(optimization_matrix),
        "baseline_targets": baseline_targets,
        "applied_targets": applied_targets,
        "energy_comparison": energy_comparison,
        "optimized_rows": optimized_rows,
        "baseline_rows": baseline_rows,
    }
