"""Ladekontext und Zeitfenster für flexible Verbraucher (Loxone, Config, Historie)."""
from __future__ import annotations

from datetime import datetime, timedelta, time

import config
from integrations import loxone_client

_LOXONE_WEEKDAY_NAMES = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
}


def _align_like(reference: datetime, dt: datetime) -> datetime:
    """Vergleichbare Datetimes: naive Config-Zeiten an reference (z. B. Matrix-Slot) anpassen."""
    if reference.tzinfo is None:
        if dt.tzinfo is None:
            return dt
        return dt.replace(tzinfo=None)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=reference.tzinfo)
    if dt.tzinfo != reference.tzinfo:
        return dt.astimezone(reference.tzinfo)
    return dt


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
        candidate = _align_like(from_dt, datetime.combine(from_dt.date(), clock))
        if candidate <= from_dt:
            candidate += timedelta(days=1)
        return candidate

    if label == "morgen":
        return _align_like(
            from_dt, datetime.combine(from_dt.date() + timedelta(days=1), clock)
        )

    target_weekday = _LOXONE_WEEKDAY_NAMES.get(label)
    if target_weekday is not None:
        for offset in range(8):
            day = from_dt.date() + timedelta(days=offset)
            if day.weekday() != target_weekday:
                continue
            candidate = _align_like(from_dt, datetime.combine(day, clock))
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
                parsed = datetime.strptime(parse_text, fmt).replace(second=0, microsecond=0)
                return _align_like(from_dt, parsed)
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
        parsed = datetime.fromtimestamp(v, tz=from_dt.tzinfo).replace(
            second=0, microsecond=0
        )
        return _align_like(from_dt, parsed)
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
        deadline = _align_like(horizon_start, datetime.combine(day, time(hour=ready_h)))
        if deadline > horizon_start:
            return deadline
    return None


def charging_deadline_after(available_from: datetime, consumer: dict) -> datetime | None:
    """Deadline (ready_by_hour) zum Ladezyklus ab prognostizierter Ankunft."""
    day_sched = config_day_schedule(consumer, available_from)
    return deadline_from_ready_hour(available_from, day_sched.get("ready_by_hour"))


def _loxone_ready_raw(consumer: dict) -> str | None:
    """Roher Loxone-String für Fertig-Uhrzeit, falls konfiguriert."""
    sched = consumer.get("charging_schedule") or {}
    lox = sched.get("loxone", {})
    io_name = lox.get("ready_by_time_name", "")
    if not io_name:
        return None
    return loxone_client.fetch_loxone_raw_value(io_name)


def _loxone_ready_deadline(
    consumer: dict,
    parse_reference: datetime,
    *,
    ready_raw: str | None = None,
) -> datetime | None:
    """Fertig-Uhrzeit aus Loxone, falls konfiguriert und parsebar."""
    if ready_raw is None:
        ready_raw = _loxone_ready_raw(consumer)
    return parse_loxone_ready_by_time(ready_raw, parse_reference)


def resolve_charging_deadline(
    consumer: dict,
    parse_reference: datetime,
    available_from: datetime,
    *,
    ready_raw: str | None = None,
) -> tuple[datetime | None, bool]:
    """
    Deadline für einen Ladezyklus: Loxone FertigUm vor Config ready_by_hour.

    parse_reference: Bezugszeitpunkt zum Parsen von FertigUm (z. B. Horizont- oder Fensterstart).

    Returns:
        (deadline, from_loxone) — from_loxone=True wenn FertigUm verwendet wurde.
    """
    loxone_deadline = _loxone_ready_deadline(
        consumer, parse_reference, ready_raw=ready_raw
    )
    if loxone_deadline is not None and loxone_deadline > available_from:
        return loxone_deadline, True
    return charging_deadline_after(available_from, consumer), False


def _window_start_for_day(
    consumer: dict, day, *, reference: datetime | None = None
) -> datetime | None:
    day_sched = config_day_schedule(consumer, datetime.combine(day, time(12, 0)))
    from_h = day_sched.get("car_available_from_hour")
    if from_h is None:
        return None
    window = datetime.combine(day, time(hour=int(from_h) % 24))
    if reference is not None:
        return _align_like(reference, window)
    return window


def next_scheduled_availability(horizon_start: datetime, consumer: dict) -> datetime | None:
    """Nächster car_available_from_hour strikt nach horizon_start."""
    for offset in range(8):
        day = horizon_start.date() + timedelta(days=offset)
        candidate = _window_start_for_day(consumer, day, reference=horizon_start)
        if candidate is not None and candidate > horizon_start:
            return candidate
    return None


def suppresses_live_charging_output(ctx: dict | None) -> bool:
    """Kein Loxone-Sollwert und keine Buchung: Prognose bei Abwesenheit ohne Anschluss."""
    if not ctx:
        return False
    return bool(ctx.get("anticipated") and not ctx.get("plugged_in"))


def resolve_absent_availability(
    horizon_start: datetime,
    consumer: dict,
    *,
    ready_raw: str | None = None,
) -> datetime | None:
    """
    Ladebeginn bei Abwesenheit: offenes Übernacht-Fenster oder nächster Termin.

    Verspätete Rückkehr am selben Tag (Slot vorbei, Auto noch abgehängt) gilt nicht
    als „jetzt verfügbar“ — es wird der nächste car_available_from_hour verwendet.
    """
    for day_offset in (0, -1):
        day = horizon_start.date() + timedelta(days=day_offset)
        window_start = _window_start_for_day(consumer, day, reference=horizon_start)
        if window_start is None or window_start > horizon_start:
            continue
        deadline, _ = resolve_charging_deadline(
            consumer,
            window_start,
            window_start,
            ready_raw=ready_raw,
        )
        if deadline is None or horizon_start >= deadline:
            continue
        if window_start.date() < horizon_start.date():
            today_from = _window_start_for_day(
                consumer, horizon_start.date(), reference=horizon_start
            )
            if today_from is not None and horizon_start >= today_from:
                continue
            return horizon_start
    return next_scheduled_availability(horizon_start, consumer)


def _loxone_inactive_context(source_label: str) -> dict:
    return {
        "active": False,
        "plugged_in": False,
        "deadline": None,
        "target_kwh": 0.0,
        "use_time_window": False,
        "source_label": source_label,
    }


def _loxone_absent_forecast_context(consumer: dict, horizon_start: datetime) -> dict:
    ready_raw = _loxone_ready_raw(consumer)
    loxone_deadline = parse_loxone_ready_by_time(ready_raw, horizon_start)
    if loxone_deadline is None:
        return _loxone_inactive_context(
            "loxone (abwesend, keine aktive Fertigstellungszeit in Loxone)"
        )
    available_from = resolve_absent_availability(
        horizon_start, consumer, ready_raw=ready_raw
    )
    if available_from is None:
        return _loxone_inactive_context(
            "loxone (abwesend, kein car_available_from_hour in Config)"
        )
    if loxone_deadline <= available_from:
        return _loxone_inactive_context(
            "loxone (abwesend, keine gültige Fertigstellungszeit)"
        )
    day_sched = config_day_schedule(consumer, available_from)
    capacity_kwh = loxone_client.resolve_consumer_battery_capacity_kwh(consumer)
    target_kwh = config.Config.target_kwh_from_rest_soc(
        consumer, day_sched.get("daily_rest_soc"), capacity_kwh=capacity_kwh
    )
    if target_kwh is None or target_kwh <= 0:
        return _loxone_inactive_context(
            "loxone (abwesend, kein Ladeziel aus daily_rest_soc)"
        )
    return {
        "active": True,
        "plugged_in": False,
        "anticipated": True,
        "available_from": available_from,
        "deadline": loxone_deadline,
        "target_kwh": round(target_kwh, 3),
        "use_time_window": False,
        "source_label": "loxone (abwesend, Prognose + FertigUm Loxone)",
    }


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
        if sched.get("forecast_when_absent"):
            return _loxone_absent_forecast_context(consumer, horizon_start)
        return _loxone_inactive_context("loxone (nicht angeschlossen)")
    ready_raw = _loxone_ready_raw(consumer)
    deadline = parse_loxone_ready_by_time(ready_raw, horizon_start)
    soc_val = (
        loxone_client.fetch_loxone_generic_value(lox.get("soc_at_plug_in_name", ""))
        if lox.get("soc_at_plug_in_name")
        else None
    )
    capacity_kwh = loxone_client.resolve_consumer_battery_capacity_kwh(consumer)
    target_kwh = config.Config.target_kwh_from_rest_soc(
        consumer, soc_val, capacity_kwh=capacity_kwh
    )
    return {
        "active": True,
        "plugged_in": True,
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
    capacity_kwh = loxone_client.resolve_consumer_battery_capacity_kwh(consumer)
    target_kwh = config.Config.target_kwh_from_rest_soc(
        consumer, rest_soc, capacity_kwh=capacity_kwh
    )
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
    *,
    live_flex_kw: dict[str, float] | None = None,
    consumers: list | None = None,
) -> dict[str, dict]:
    """Ladekontext je Verbraucher mit charging_schedule für den Optimierungshorizont."""
    from . import charge_immediate as ci

    logged_simulation = bool(
        optimization_matrix
        and optimization_matrix[0].get("consumption_mode") == "logged_day"
    )
    active = consumers if consumers is not None else config.get_flexible_consumers(
        optimizer_only=True
    )
    horizon = len(optimization_matrix) if optimization_matrix else 24
    contexts: dict[str, dict] = {}
    for consumer in active:
        if not charging_schedule_enabled(consumer):
            continue
        cid = consumer["id"]
        contexts[cid] = resolve_charging_context(
            consumer,
            optimization_matrix,
            consumer_daily_targets_kwh,
            logged_simulation,
        )
        live_kw = (live_flex_kw or {}).get(cid)
        contexts[cid] = ci.enrich_context_with_immediate_charge(
            consumer,
            contexts[cid],
            live_kw=live_kw,
            horizon=horizon,
        )
    return contexts


def hours_needed_to_deliver(remaining_kwh: float, max_kw: float) -> float:
    """Benötigte Volllast-Stunden für verbleibende Energie (5 % Puffer)."""
    if max_kw <= 1e-9 or remaining_kwh <= 1e-9:
        return 0.0
    return (remaining_kwh / max_kw) * 1.05


def latest_start_datetime(
    deadline: datetime,
    remaining_kwh: float,
    max_kw: float,
) -> datetime:
    """Spätester Beginn, damit remaining_kwh vor deadline bei max_kw geliefert werden kann."""
    hours = hours_needed_to_deliver(remaining_kwh, max_kw)
    if hours <= 0:
        return deadline
    return deadline - timedelta(hours=hours)


def split_eligible_by_urgent_deadline(
    matrix: list,
    eligible_indices: list[int],
    deadline: datetime,
    remaining_kwh: float,
    max_kw: float,
) -> tuple[list[int], list[int]]:
    """
    Teilt zulässige Slots in optional (vor spätestem Ladebeginn) und urgent (bis Deadline).

    Optional: Laden erlaubt, aber nicht erzwungen (z. B. günstige Preise).
    Urgent: Muss die noch offene Restenergie liefern, falls vorher nicht genug geladen wurde.

    Fallback: Liegt kein Slot im urgent-Bereich, gelten alle eligible als urgent.
    """
    if not eligible_indices or remaining_kwh <= 1e-9:
        return [], []
    must_start = latest_start_datetime(deadline, remaining_kwh, max_kw)
    pre_urgent: list[int] = []
    urgent: list[int] = []
    for t in eligible_indices:
        slot_dt = matrix_slot_datetime(matrix, t)
        if slot_dt >= deadline:
            continue
        if slot_dt < must_start:
            pre_urgent.append(t)
        else:
            urgent.append(t)
    if not urgent:
        return [], list(eligible_indices)
    return pre_urgent, urgent


def urgent_charging_indices(
    matrix: list,
    eligible_indices: list[int],
    deadline: datetime,
    remaining_kwh: float,
    max_kw: float,
) -> list[int]:
    """Horizont-Slots ab spätestem Ladebeginn bis Deadline (Nachhol-Fenster)."""
    _, urgent = split_eligible_by_urgent_deadline(
        matrix, eligible_indices, deadline, remaining_kwh, max_kw
    )
    return urgent


URGENT_PLAN_KWH_EPSILON = 0.05


def summarize_urgent_rule_usage(
    *,
    pre_urgent_indices: list[int],
    urgent_indices: list[int],
    effective_target_kwh: float,
    planned_pre_urgent_kwh: float,
    planned_urgent_kwh: float,
    deadline: datetime | None,
    must_start: datetime | None,
) -> dict:
    """
    Klassifiziert die Wirkung der urgent-Nebenbedingung im MILP-Plan.

    role:
      - nicht_aktiv: keine Deadline / kein Ladeziel / keine urgent-Slots
      - nur_urgent_fenster: kein optionaler Vorlauf (Horizont beginnt im urgent-Fenster)
      - nachholen: Energie wird im urgent-Fenster nachgeholt
      - redundant: Ziel wird ohne urgent-Fenster erreicht (Nebenbedingung wirkungslos)
    """
    if effective_target_kwh <= URGENT_PLAN_KWH_EPSILON or not urgent_indices:
        return {"role": "nicht_aktiv"}

    summary: dict = {
        "role": "redundant",
        "target_kwh": round(float(effective_target_kwh), 3),
        "planned_pre_urgent_kwh": round(float(planned_pre_urgent_kwh), 3),
        "planned_urgent_kwh": round(float(planned_urgent_kwh), 3),
    }
    if deadline is not None:
        summary["deadline"] = deadline.isoformat(timespec="seconds")
    if must_start is not None:
        summary["must_start"] = must_start.isoformat(timespec="seconds")

    if not pre_urgent_indices:
        summary["role"] = "nur_urgent_fenster"
    elif planned_urgent_kwh > URGENT_PLAN_KWH_EPSILON:
        summary["role"] = "nachholen"
    else:
        summary["role"] = "redundant"
    return summary


def schedule_indices_for_consumer(
    matrix: list,
    horizon: int,
    default_indices: list[int],
    consumer: dict,
    charging_context: dict | None,
) -> list[int]:
    """Tages- oder Deadline-Horizont: bei Fertigstellungszeit alle Slots bis Deadline."""
    ctx = charging_context or {}
    deadline = ctx.get("deadline")
    if ctx.get("active", True) and isinstance(deadline, datetime):
        return consumer_charging_eligible_indices(
            matrix, consumer, list(range(horizon)), ctx
        )
    return default_indices


def serialize_charging_contexts(contexts: dict[str, dict]) -> dict[str, dict]:
    """Datetime-Felder für JSON-Logs in ISO-Strings wandeln."""
    serialized: dict[str, dict] = {}
    for cid, ctx in contexts.items():
        row = dict(ctx)
        for key in ("deadline", "available_from"):
            value = row.get(key)
            if isinstance(value, datetime):
                row[key] = value.isoformat(timespec="seconds")
        serialized[cid] = row
    return serialized


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
    available_from = ctx.get("available_from")
    for t in schedule_indices:
        slot_dt = matrix_slot_datetime(matrix, t)
        if available_from is not None and slot_dt < available_from:
            continue
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
    consumer_power_vars: dict[str, list] | None = None,
    consumer_pv_follow_vars: dict[str, list] | None = None,
) -> list[int]:
    """Setzt MILP-Nebenbedingungen für Ladezeitfenster; liefert die zulässigen Stunden."""
    cid = consumer["id"]
    eligible = consumer_charging_eligible_indices(
        matrix, consumer, schedule_indices, charging_context
    )
    blocked = set(schedule_indices) - set(eligible)
    for t in blocked:
        prob += consumer_on[cid][t] == 0
        if consumer_power_vars and cid in consumer_power_vars:
            prob += consumer_power_vars[cid][t] == 0
        if consumer_pv_follow_vars and cid in consumer_pv_follow_vars:
            prob += consumer_pv_follow_vars[cid][t] == 0
    return eligible
