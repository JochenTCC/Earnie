"""Ladekontext und Zeitfenster für flexible Verbraucher (Loxone, Config, Historie)."""
from __future__ import annotations

from datetime import datetime, timedelta, time

import config
import loxone_client

_LOXONE_WEEKDAY_NAMES = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
}


def matrix_slot_datetime(matrix: list, index: int) -> datetime:
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


def matrix_charging_anchor(matrix: list) -> datetime | None:
    """Expliziter Abfahrt-/Fertig-Zeitpunkt (Backtesting-Fenster-Ende), falls gesetzt."""
    if not matrix:
        return None
    anchor = matrix[0].get("charging_anchor")
    if isinstance(anchor, datetime):
        return anchor.replace(minute=0, second=0, microsecond=0)
    return None


def charging_schedule_enabled(consumer: dict) -> bool:
    sched = consumer.get("charging_schedule")
    return bool(sched and sched.get("enabled"))


def schedule_day_key(dt: datetime) -> str:
    return "weekend" if dt.weekday() >= 5 else "weekday"


def config_day_schedule(consumer: dict, dt: datetime) -> dict:
    sched = consumer.get("charging_schedule") or {}
    return sched.get(schedule_day_key(dt), {}) or {}


def parse_loxone_time_hm(text: str) -> time | None:
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(text.strip(), fmt)
            return parsed.time().replace(second=0, microsecond=0)
        except ValueError:
            continue
    return None


def parse_loxone_relative_ready_by(text: str, from_dt: datetime) -> datetime | None:
    """Parst Loxone-Relative wie 'Heute, 23:30', 'Morgen, 06:00', 'Montag, 12:30'."""
    if ", " not in text:
        return None
    label, time_part = text.split(", ", 1)
    label = label.strip().lower()
    clock = parse_loxone_time_hm(time_part)
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


def parse_loxone_ready_by_time(value: str | float | None, from_dt: datetime) -> datetime | None:
    """Wandelt einen Loxone-Zeitwert (relativ/absolut oder Legacy-Zahl) in eine Deadline um."""
    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        relative = parse_loxone_relative_ready_by(text, from_dt)
        if relative is not None:
            return relative

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


def deadline_from_ready_hour(horizon_start: datetime, ready_hour: int | None) -> datetime | None:
    if ready_hour is None:
        return None
    ready_h = int(ready_hour) % 24
    for offset in range(8):
        day = horizon_start.date() + timedelta(days=offset)
        deadline = datetime.combine(day, time(hour=ready_h))
        if deadline > horizon_start:
            return deadline
    return None


def fetch_loxone_charging_context(consumer: dict, horizon_start: datetime) -> dict:
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
    deadline = parse_loxone_ready_by_time(ready_raw, horizon_start)
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


def historical_charging_context(
    consumer: dict,
    matrix: list,
    consumer_daily_targets_kwh: dict | None,
    horizon_start: datetime,
    *,
    realtime: bool,
) -> dict:
    from . import targets as optimizer_targets

    charging_anchor = matrix_charging_anchor(matrix)
    schedule_ref = charging_anchor or horizon_start
    day_sched = config_day_schedule(consumer, schedule_ref)
    targets = optimizer_targets.resolve_horizon_consumer_targets_kwh(
        matrix, consumer_daily_targets_kwh
    )
    target_kwh = float(targets.get(consumer["id"], 0.0))
    if charging_anchor is not None:
        deadline = charging_anchor
    else:
        deadline = deadline_from_ready_hour(horizon_start, day_sched.get("ready_by_hour"))
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


def resolve_charging_context(
    consumer: dict,
    matrix: list,
    consumer_daily_targets_kwh: dict | None,
    logged_simulation: bool,
) -> dict:
    sched = consumer.get("charging_schedule")
    if not sched or not sched.get("enabled"):
        return {"active": True, "deadline": None, "target_kwh": None, "use_time_window": False}
    horizon_start = matrix_slot_datetime(matrix, 0)
    target_source = consumer.get("daily_target_source", "config")
    if logged_simulation or target_source == "historical":
        return historical_charging_context(
            consumer,
            matrix,
            consumer_daily_targets_kwh,
            horizon_start,
            realtime=not logged_simulation,
        )
    if target_source == "loxone":
        return fetch_loxone_charging_context(consumer, horizon_start)
    day_sched = config_day_schedule(consumer, horizon_start)
    rest_soc = day_sched.get("daily_rest_soc")
    target_kwh = config.Config.target_kwh_from_rest_soc(consumer, rest_soc)
    return {
        "active": True,
        "deadline": deadline_from_ready_hour(horizon_start, day_sched.get("ready_by_hour")),
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
        if not charging_schedule_enabled(consumer):
            continue
        contexts[consumer["id"]] = resolve_charging_context(
            consumer,
            optimization_matrix,
            consumer_daily_targets_kwh,
            logged_simulation,
        )
    return contexts


def apply_horizon_charging_limits(
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


def hour_in_charging_window(hour: int, available_from_h: int, ready_by_h: int) -> bool:
    """Prüft Ladezeitfenster: ab car_available_from_hour bis ready_by_hour (exklusiv, Mitternacht-Sprung)."""
    available_from_h %= 24
    ready_by_h %= 24
    if available_from_h == ready_by_h:
        return True
    if available_from_h < ready_by_h:
        return available_from_h <= hour < ready_by_h
    return hour >= available_from_h or hour < ready_by_h


def consumer_charging_eligible_indices(
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
    if charging_context is None and not charging_schedule_enabled(consumer):
        return list(schedule_indices)
    ctx = charging_context or {}
    deadline = ctx.get("deadline")
    if deadline is None and charging_schedule_enabled(consumer):
        horizon_start = matrix_slot_datetime(matrix, 0)
        day_sched = ctx.get("config_day_schedule") or config_day_schedule(consumer, horizon_start)
        deadline = deadline_from_ready_hour(horizon_start, day_sched.get("ready_by_hour"))
    use_time_window = bool(ctx.get("use_time_window"))
    eligible = []
    for t in schedule_indices:
        slot_dt = matrix_slot_datetime(matrix, t)
        if deadline is not None and slot_dt >= deadline:
            continue
        if not use_time_window:
            eligible.append(t)
            continue
        day_sched = ctx.get("config_day_schedule") or config_day_schedule(consumer, slot_dt)
        from_h = day_sched.get("car_available_from_hour")
        until_h = day_sched.get("ready_by_hour")
        if from_h is None and until_h is None:
            eligible.append(t)
            continue
        from_h = int(from_h) if from_h is not None else 0
        until_h = int(until_h) if until_h is not None else 24
        if hour_in_charging_window(slot_dt.hour, from_h, until_h):
            eligible.append(t)
    return eligible


def apply_charging_window_constraints(
    prob,
    consumer_on: dict[str, list],
    matrix: list,
    consumer: dict,
    schedule_indices: list[int],
    charging_context: dict | None = None,
) -> list[int]:
    """Setzt MILP-Nebenbedingungen für Ladezeitfenster; liefert die zulässigen Stunden."""
    cid = consumer["id"]
    eligible = consumer_charging_eligible_indices(
        matrix, consumer, schedule_indices, charging_context
    )
    blocked = set(schedule_indices) - set(eligible)
    for t in blocked:
        prob += consumer_on[cid][t] == 0
    return eligible
