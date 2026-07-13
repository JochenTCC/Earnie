"""Schedule-Logik für allgemeine Verbraucher (type generic)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

WEEKS_PER_YEAR = 52
DEFAULT_START_HOUR = 12
MAX_START_SHIFT_H = 12.0
LEGACY_FLEX_TO_SHIFT = {
    "fixed": 0.0,
    "day": 12.0,
    "any": 12.0,
}


def is_fixed_start(start_shift_h: float) -> bool:
    return float(start_shift_h) <= 0.0


def is_fully_flexible(start_shift_h: float) -> bool:
    return float(start_shift_h) >= MAX_START_SHIFT_H


def eligible_start_hours(start_hour: int, start_shift_h: float) -> frozenset[int]:
    """Erlaubte Startstunden pro Tag (mod 24). shift >= 12 → alle 24 h."""
    if is_fully_flexible(start_shift_h):
        return frozenset(range(24))
    center = int(start_hour) % 24
    shift = int(float(start_shift_h))
    return frozenset((center + offset) % 24 for offset in range(-shift, shift + 1))


def migrate_start_flexibility(schedule: dict) -> dict:
    """Überführt legacy start_flexibility in start_shift_h."""
    out = dict(schedule)
    if "start_shift_h" in out and out.get("start_shift_h") is not None:
        return out
    legacy = str(out.pop("start_flexibility", "day")).strip().lower()
    out["start_shift_h"] = LEGACY_FLEX_TO_SHIFT.get(legacy, 12.0)
    return out


def derive_duration_h(consumer: dict) -> float | None:
    """Rückrechnung duration_h aus annual_kwh wenn im Schedule fehlend."""
    schedule = consumer.get("schedule") or {}
    duration = float(schedule.get("duration_h", 0.0) or 0.0)
    if duration > 0:
        return duration
    runs = int(schedule.get("runs_per_week", 0) or 0)
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    annual = float(consumer.get("annual_kwh", 0.0) or 0.0)
    if runs <= 0 or nominal <= 0 or annual <= 0:
        return None
    denominator = nominal * runs * WEEKS_PER_YEAR
    if denominator <= 0:
        return None
    return annual / denominator


def validate_generic_schedule(schedule: dict, *, runs_per_week: int) -> None:
    if runs_per_week <= 0:
        return
    duration = float(schedule.get("duration_h", 0.0) or 0.0)
    if duration <= 0:
        raise ValueError("schedule.duration_h muss > 0 sein wenn runs_per_week > 0.")
    if schedule.get("start_hour") is None:
        raise ValueError("schedule.start_hour ist Pflicht wenn runs_per_week > 0.")
    start_hour = int(schedule["start_hour"])
    if start_hour < 0 or start_hour > 23:
        raise ValueError("schedule.start_hour muss zwischen 0 und 23 liegen.")
    shift = float(schedule.get("start_shift_h", 0.0) or 0.0)
    if shift < 0 or shift > MAX_START_SHIFT_H:
        raise ValueError(
            f"schedule.start_shift_h muss zwischen 0 und {MAX_START_SHIFT_H:g} liegen."
        )


def normalize_generic_schedule(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    runs = int(raw.get("runs_per_week", 0) or 0)
    if runs <= 0:
        return None
    migrated = migrate_start_flexibility(raw)
    duration = float(migrated.get("duration_h", 0.0) or 0.0)
    start_hour_raw = migrated.get("start_hour")
    start_hour = DEFAULT_START_HOUR if start_hour_raw is None else int(start_hour_raw) % 24
    start_shift_h = max(0.0, min(MAX_START_SHIFT_H, float(migrated.get("start_shift_h", 0.0) or 0.0)))
    schedule = {
        "runs_per_week": max(0, runs),
        "duration_h": max(0.0, duration),
        "start_hour": start_hour,
        "start_shift_h": start_shift_h,
    }
    validate_generic_schedule(schedule, runs_per_week=runs)
    return schedule


def generic_annual_kwh(consumer: dict) -> float:
    if consumer.get("profile_csv"):
        return float(consumer.get("annual_kwh", 0.0) or 0.0)
    schedule = consumer.get("schedule")
    if not schedule:
        return float(consumer.get("annual_kwh", 0.0) or 0.0)
    runs = int(schedule.get("runs_per_week", 0) or 0)
    if runs <= 0:
        return 0.0
    duration = float(schedule.get("duration_h", 0.0) or 0.0)
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    if duration <= 0 or nominal <= 0:
        return float(consumer.get("annual_kwh", 0.0) or 0.0)
    return nominal * duration * runs * WEEKS_PER_YEAR


def run_weekdays_for_day(day: date, runs_per_week: int) -> int:
    """Wie viele Läufe an diesem Kalendertag (gleichmäßige Verteilung über die Woche)."""
    if runs_per_week <= 0:
        return 0
    if runs_per_week >= 7:
        return runs_per_week // 7 + (1 if day.weekday() < runs_per_week % 7 else 0)
    step = 7 / runs_per_week
    for run_index in range(runs_per_week):
        weekday = int(run_index * step) % 7
        if weekday == day.weekday():
            return 1
    return 0


def _apply_run_block(hourly: list[float], start_hour: int, duration_h: float, power_kw: float) -> None:
    duration_slots = max(1, int(round(duration_h)))
    for offset in range(duration_slots):
        hour = (start_hour + offset) % 24
        hourly[hour] += power_kw


def generic_hourly_kw_for_day(consumer: dict, day: date) -> list[float]:
    """Baseline-Tagesprofil: Läufe an Referenz-start_hour."""
    hourly = [0.0] * 24
    schedule = consumer.get("schedule")
    if not schedule:
        return hourly
    runs = int(schedule.get("runs_per_week", 0) or 0)
    if runs <= 0:
        return hourly
    duration_h = float(schedule.get("duration_h", 0.0) or 0.0)
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    start_hour = int(schedule.get("start_hour", DEFAULT_START_HOUR)) % 24
    if duration_h <= 0 or nominal <= 0:
        return hourly
    run_count = run_weekdays_for_day(day, runs)
    for _ in range(run_count):
        _apply_run_block(hourly, start_hour, duration_h, nominal)
    return hourly


def generic_daily_target_kwh_for_day(consumer: dict, day: date) -> float:
    """Tagesenergie aus Anzahl Läufe an diesem Tag."""
    schedule = consumer.get("schedule")
    if not schedule:
        return 0.0
    duration_h = float(schedule.get("duration_h", 0.0) or 0.0)
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    runs = int(schedule.get("runs_per_week", 0) or 0)
    if duration_h <= 0 or nominal <= 0 or runs <= 0:
        return 0.0
    run_count = run_weekdays_for_day(day, runs)
    return nominal * duration_h * run_count


def generic_reference_run_end(day: date, start_hour: int, duration_h: float) -> datetime:
    """Ende des Referenz-Laufs (start_hour + duration_h) am Kalendertag."""
    duration_slots = max(1, int(round(duration_h)))
    end_hour = int(start_hour) + duration_slots
    if end_hour < 24:
        return datetime.combine(day, time(hour=end_hour % 24))
    return datetime.combine(day + timedelta(days=1), time(hour=end_hour % 24))


def generic_daily_target_kwh_for_window_day(
    consumer: dict,
    day: date,
    slot_datetimes: list[datetime],
    window_end: datetime,
) -> float:
    """
    Tagesenergie nur wenn der Referenz-Lauf vor window_end enden kann und
    mindestens eine erlaubte Stunde im Fenster liegt (07:00-Anker).
    """
    day_kwh = generic_daily_target_kwh_for_day(consumer, day)
    if day_kwh <= 0.0:
        return 0.0
    schedule = consumer.get("schedule") or {}
    duration_h = float(schedule.get("duration_h", 0.0) or 0.0)
    if duration_h <= 0.0:
        return 0.0
    start_hour = int(schedule.get("start_hour", DEFAULT_START_HOUR)) % 24
    start_shift_h = float(schedule.get("start_shift_h", 0.0) or 0.0)
    hours_in_window = {slot_dt.hour for slot_dt in slot_datetimes if slot_dt.date() == day}
    if not hours_in_window:
        return 0.0
    allowed = generic_allowed_slot_hours(start_hour, start_shift_h, duration_h)
    if not (hours_in_window & allowed):
        return 0.0
    if generic_reference_run_end(day, start_hour, duration_h) > window_end:
        return 0.0
    return day_kwh


def generic_flex_target_kwh_for_window(
    consumer: dict,
    slot_datetimes: list[datetime],
    window_end: datetime,
) -> float:
    """Summiert lieferbare Generic-Flex-kWh über alle Kalendertage im Fenster."""
    if not slot_datetimes:
        return 0.0
    dates = {slot_dt.date() for slot_dt in slot_datetimes}
    total = sum(
        generic_daily_target_kwh_for_window_day(consumer, day, slot_datetimes, window_end)
        for day in dates
    )
    return round(total, 3)


def generic_allowed_slot_hours(
    start_hour: int,
    start_shift_h: float,
    duration_h: float,
) -> frozenset[int]:
    """Stunden 0–23, in denen der Lauf liegen darf (Start im Fenster, Dauer im selben Tag)."""
    duration_slots = max(1, int(round(duration_h)))
    allowed: set[int] = set()
    for start in eligible_start_hours(start_hour, start_shift_h):
        for offset in range(duration_slots):
            hour = start + offset
            if hour < 24:
                allowed.add(hour)
    return frozenset(allowed)


def format_start_window_caption(start_hour: int, start_shift_h: float) -> str:
    if is_fully_flexible(start_shift_h):
        return "Startzeitpunkt vollständig frei (Verschiebung 12 h)."
    if is_fixed_start(start_shift_h):
        return f"Fixer Start um {start_hour:02d}:00 Uhr."
    hours = sorted(eligible_start_hours(start_hour, start_shift_h))
    if len(hours) == 1:
        return f"Erlaubter Start: {hours[0]:02d}:00 Uhr."
    return f"Erlaubter Start: {hours[0]:02d}:00–{hours[-1]:02d}:00 Uhr."
