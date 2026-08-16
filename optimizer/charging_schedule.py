"""Zeitfenster, Deadlines und Schedule-Hilfen für Ladekontexte."""
from __future__ import annotations

from datetime import datetime, timedelta, time

from integrations import loxone_client
from settings.ehal_marker_resolve import marker_get_evcs_ready_by_time

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


def _deadline_from_unix(unix_ts: float, from_dt: datetime) -> datetime:
    tz = from_dt.tzinfo
    if tz is None:
        import config
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(config.get_planning_timezone())
    parsed = datetime.fromtimestamp(unix_ts, tz=tz).replace(second=0, microsecond=0)
    if from_dt.tzinfo is None:
        parsed = parsed.replace(tzinfo=None)
    return _align_like(from_dt, parsed)


def _strip_short_weekday_prefix(text: str) -> str:
    """Legacy 'Mo, 12:34' → '12:34' when the prefix isn't a full weekday/heute/morgen token."""
    if ", " not in text:
        return text
    prefix, remainder = text.split(", ", 1)
    low = prefix.strip().lower()
    if low in _LOXONE_WEEKDAY_NAMES or low in ("heute", "morgen"):
        return text
    if len(prefix) <= 3 and remainder.strip():
        return remainder.strip()
    return text


def _parse_loxone_ready_by_text(text: str, from_dt: datetime) -> datetime | None:
    # Prefer numeric Unix (SpecialState10 path may arrive as str).
    try:
        as_num = float(text.replace(",", "."))
    except ValueError:
        as_num = None
    if as_num is not None and as_num > 1_000_000_000:
        return _deadline_from_unix(as_num, from_dt)

    # Backup: AlarmClock Tna relative/absolute text (Heute/Morgen/Wochentag).
    relative = parse_loxone_relative_ready_by(text, from_dt)
    if relative is not None:
        return relative

    parse_text = _strip_short_weekday_prefix(text)
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


def _parse_loxone_ready_by_number(v: float, from_dt: datetime) -> datetime | None:
    if v > 1_000_000_000:
        return _deadline_from_unix(v, from_dt)
    if 0 <= v < 24:
        hour = int(v)
        minute = int(round((v - hour) * 60)) % 60
    elif 0 <= v < 2400 and abs(v - int(v)) < 1e-6:
        hour = int(v) // 100
        minute = int(v) % 100
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


def parse_loxone_ready_by_time(value: str | float | None, from_dt: datetime) -> datetime | None:
    """Wandelt Loxone FertigUm (Unix, Tna-Text-Backup, Legacy-Zahl) in eine Deadline um."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return _parse_loxone_ready_by_text(text, from_dt)
    return _parse_loxone_ready_by_number(float(value), from_dt)


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


def _loxone_ready_raw(consumer: dict) -> str | float | None:
    """Fertig-Uhrzeit roh: Unix (SpecialState10) oder Tna-/Merker-Text."""
    io_name = marker_get_evcs_ready_by_time(consumer)
    if not io_name:
        return None
    return loxone_client.fetch_loxone_ready_by_time(io_name)



def _facade_loxone_ready_raw(consumer: dict) -> str | float | None:
    """Lookup via charging_context so tests can patch cc._loxone_ready_raw."""
    from optimizer import charging_context as cc

    return cc._loxone_ready_raw(consumer)


def _loxone_ready_deadline(
    consumer: dict,
    parse_reference: datetime,
    *,
    ready_raw: str | float | None = None,
) -> datetime | None:
    """Fertig-Uhrzeit aus Loxone, falls konfiguriert und parsebar."""
    if ready_raw is None:
        ready_raw = _facade_loxone_ready_raw(consumer)
    return parse_loxone_ready_by_time(ready_raw, parse_reference)


def resolve_charging_deadline(
    consumer: dict,
    parse_reference: datetime,
    available_from: datetime,
    *,
    ready_raw: str | float | None = None,
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


def hour_in_charging_window(hour: int, available_from_h: int, ready_by_h: int) -> bool:
    """Prüft Ladezeitfenster: ab car_available_from_hour bis ready_by_hour (exklusiv, Mitternacht-Sprung)."""
    available_from_h %= 24
    ready_by_h %= 24
    if available_from_h == ready_by_h:
        return True
    if available_from_h < ready_by_h:
        return available_from_h <= hour < ready_by_h
    return hour >= available_from_h or hour < ready_by_h


def _is_slot_charging_eligible(
    t: int,
    matrix: list,
    consumer: dict,
    ctx: dict,
    *,
    deadline: datetime | None,
    available_from: datetime | None,
    use_time_window: bool,
) -> bool:
    slot_dt = matrix_slot_datetime(matrix, t)
    if available_from is not None and slot_dt < available_from:
        return False
    if deadline is not None and slot_dt >= deadline:
        return False
    if not use_time_window:
        return True
    day_sched = ctx.get("config_day_schedule") or config_day_schedule(consumer, slot_dt)
    from_h = day_sched.get("car_available_from_hour")
    until_h = day_sched.get("ready_by_hour")
    if from_h is None and until_h is None:
        return True
    from_h = int(from_h) if from_h is not None else 0
    until_h = int(until_h) if until_h is not None else 24
    return hour_in_charging_window(slot_dt.hour, from_h, until_h)


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
    available_from = ctx.get("available_from")
    return [
        t
        for t in schedule_indices
        if _is_slot_charging_eligible(
            t,
            matrix,
            consumer,
            ctx,
            deadline=deadline,
            available_from=available_from,
            use_time_window=use_time_window,
        )
    ]


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
