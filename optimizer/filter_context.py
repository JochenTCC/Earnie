"""Natives Filterfenster (SwimSpa) — gesperrte MILP-Slots außerhalb Ernie-Zusatzläufen."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, time

import config
from integrations import loxone_client
from .charging_context import consumer_charging_eligible_indices, matrix_slot_datetime

logger = logging.getLogger(__name__)


def filter_schedule_enabled(consumer: dict) -> bool:
    sched = consumer.get("filter_schedule")
    return bool(sched and sched.get("enabled"))


def slot_in_native_window(
    slot_dt: datetime,
    start_hour: float,
    duration_hours: float,
) -> bool:
    """True wenn slot_dt im halboffenen Intervall [Start, Start+Dauer) eines Tages liegt."""
    if duration_hours <= 0:
        return False
    day_start = datetime.combine(
        slot_dt.date(),
        time(hour=int(start_hour) % 24, minute=0, second=0, microsecond=0),
    )
    window_end = day_start + timedelta(hours=duration_hours)
    if day_start <= slot_dt < window_end:
        return True
    prev_start = day_start - timedelta(days=1)
    prev_end = prev_start + timedelta(hours=duration_hours)
    return prev_start <= slot_dt < prev_end


def native_blocked_indices(
    matrix: list,
    schedule_indices: list[int],
    start_hour: float,
    duration_hours: float,
) -> list[int]:
    blocked: list[int] = []
    for t in schedule_indices:
        if t < 0 or t >= len(matrix):
            continue
        slot_dt = matrix_slot_datetime(matrix, t)
        if slot_in_native_window(slot_dt, start_hour, duration_hours):
            blocked.append(t)
    return blocked


def resolve_native_window(
    consumer: dict,
    logged_simulation: bool,
) -> tuple[float | None, float | None, str]:
    """Start-Stunde und Dauer des nativen Duty-Cycles (Loxone oder config_fallback)."""
    sched = consumer.get("filter_schedule") or {}
    fallback = sched.get("config_fallback") or {}
    fb_start = fallback.get("native_start_hour")
    fb_duration = fallback.get("native_duration_hours")

    if logged_simulation:
        if fb_start is not None and fb_duration is not None:
            return float(fb_start), float(fb_duration), "config_fallback"
        logger.warning(
            "Verbraucher '%s': filter_schedule.config_fallback unvollständig — "
            "keine natives Fenster-Sperrung.",
            consumer.get("id"),
        )
        return None, None, "config_fallback (fehlend)"

    lox = sched.get("loxone") or {}
    start_name = lox.get("native_start_hour_name", "")
    duration_name = lox.get("native_duration_hours_name", "")
    start = duration = None
    start_format = "missing"
    if start_name:
        start, start_format, raw_start = loxone_client.fetch_filter_native_start_hour(start_name)
        if start is not None:
            logger.info(
                "Verbraucher '%s': natives Filterfenster Start=%.0f h (Format=%s, raw=%r).",
                consumer.get("id"),
                start,
                start_format,
                raw_start,
            )
    if duration_name:
        duration = loxone_client.fetch_loxone_generic_value(duration_name)
    if start is not None and duration is not None and float(duration) > 0:
        return float(start), float(duration), "loxone"

    if fb_start is not None and fb_duration is not None:
        logger.warning(
            "Verbraucher '%s': natives Filterfenster aus Loxone nicht lesbar — "
            "config_fallback (Start=%s, Dauer=%s h).",
            consumer.get("id"),
            fb_start,
            fb_duration,
        )
        return float(fb_start), float(fb_duration), "config_fallback"

    logger.warning(
        "Verbraucher '%s': natives Filterfenster weder aus Loxone noch Fallback — "
        "keine Slot-Sperrung.",
        consumer.get("id"),
    )
    return None, None, "unbekannt"


def resolve_filter_context(
    consumer: dict,
    matrix: list,
    logged_simulation: bool,
) -> dict:
    start, duration, source_label = resolve_native_window(consumer, logged_simulation)
    horizon = len(matrix)
    schedule = list(range(horizon))
    if start is None or duration is None:
        return {
            "active": True,
            "native_start_hour": start,
            "native_duration_hours": duration,
            "blocked_indices": [],
            "source_label": source_label,
        }
    blocked = native_blocked_indices(matrix, schedule, start, duration)
    return {
        "active": True,
        "native_start_hour": start,
        "native_duration_hours": duration,
        "blocked_indices": blocked,
        "source_label": source_label,
    }


def resolve_filter_contexts(
    optimization_matrix: list,
    consumers: list | None = None,
) -> dict[str, dict]:
    logged_simulation = bool(
        optimization_matrix
        and optimization_matrix[0].get("consumption_mode") == "logged_day"
    )
    active = consumers if consumers is not None else config.get_flexible_consumers(
        optimizer_only=True
    )
    contexts: dict[str, dict] = {}
    for consumer in active:
        if not filter_schedule_enabled(consumer):
            continue
        cid = consumer["id"]
        contexts[cid] = resolve_filter_context(
            consumer, optimization_matrix, logged_simulation
        )
    return contexts


def consumer_flex_eligible_indices(
    matrix: list,
    consumer: dict,
    schedule_indices: list[int],
    charging_context: dict | None,
    filter_context: dict | None,
) -> list[int]:
    """Zulässige Slots nach Ladezeitfenster minus natives Filterfenster."""
    eligible = consumer_charging_eligible_indices(
        matrix, consumer, schedule_indices, charging_context
    )
    if not filter_context or not filter_schedule_enabled(consumer):
        return eligible
    blocked = set(filter_context.get("blocked_indices", []))
    return [t for t in eligible if t not in blocked]


def apply_slot_availability_constraints(
    prob,
    consumer_on: dict[str, list],
    consumer: dict,
    schedule_indices: list[int],
    eligible_indices: list[int],
    consumer_power_vars: dict[str, list] | None = None,
    consumer_pv_follow_vars: dict[str, list] | None = None,
) -> list[int]:
    """Setzt MILP-Nebenbedingungen: Verbraucher nur in eligible_indices aktiv."""
    cid = consumer["id"]
    blocked = set(schedule_indices) - set(eligible_indices)
    for t in blocked:
        prob += consumer_on[cid][t] == 0
        if consumer_power_vars and cid in consumer_power_vars:
            prob += consumer_power_vars[cid][t] == 0
        if consumer_pv_follow_vars and cid in consumer_pv_follow_vars:
            prob += consumer_pv_follow_vars[cid][t] == 0
    return eligible_indices
