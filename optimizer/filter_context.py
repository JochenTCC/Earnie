"""Natives Filterfenster (SwimSpa) — gesperrte MILP-Slots außerhalb Ernie-Zusatzläufen."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import config
from integrations import loxone_client
from .charging_context import consumer_charging_eligible_indices, matrix_slot_datetime

logger = logging.getLogger(__name__)


def filter_schedule_enabled(consumer: dict) -> bool:
    sched = consumer.get("filter_schedule")
    return bool(sched and sched.get("enabled"))


def _wall_clock_slot(slot_dt: datetime) -> datetime:
    """Vergleichsfähiger Stunden-Slot als naive Ortszeit (Planungs-TZ)."""
    slot_dt = slot_dt.replace(minute=0, second=0, microsecond=0)
    if slot_dt.tzinfo is None:
        return slot_dt
    tz = ZoneInfo(config.get_planning_timezone())
    return slot_dt.astimezone(tz).replace(tzinfo=None)


def slot_in_native_window(
    slot_dt: datetime,
    start_hour: float,
    duration_hours: float,
) -> bool:
    """True wenn slot_dt im halboffenen Intervall [Start, Start+Dauer) eines Tages liegt."""
    if duration_hours <= 0:
        return False
    slot_dt = _wall_clock_slot(slot_dt)
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
) -> tuple[float | None, float | None, str, dict | None]:
    """Start-Stunde und Dauer des nativen Duty-Cycles (Loxone oder config_fallback).

    Rückgabe: (start_hour, duration_hours, source_label, log_extra).
    log_extra enthält format/raw nur bei erfolgreichem Loxone-Lesen (für einmaliges INFO-Log).
    """
    sched = consumer.get("filter_schedule") or {}
    fallback = sched.get("config_fallback") or {}
    fb_start = fallback.get("native_start_hour")
    fb_duration = fallback.get("native_duration_hours")

    if logged_simulation:
        if fb_start is not None and fb_duration is not None:
            return float(fb_start), float(fb_duration), "config_fallback", None
        logger.warning(
            "Verbraucher '%s': filter_schedule.config_fallback unvollständig — "
            "keine natives Fenster-Sperrung.",
            consumer.get("id"),
        )
        return None, None, "config_fallback (fehlend)", None

    lox = sched.get("loxone") or {}
    start_name = lox.get("native_start_hour_name", "")
    duration_name = lox.get("native_duration_hours_name", "")
    start = duration = None
    start_format = "missing"
    log_extra = None
    if start_name:
        start, start_format, raw_start = loxone_client.fetch_filter_native_start_hour(start_name)
        if start is not None:
            log_extra = {"format": start_format, "raw": raw_start}
    if duration_name:
        duration = loxone_client.fetch_loxone_generic_value(duration_name)
    if start is not None and duration is not None and float(duration) > 0:
        return float(start), float(duration), "loxone", log_extra

    if fb_start is not None and fb_duration is not None:
        logger.warning(
            "Verbraucher '%s': natives Filterfenster aus Loxone nicht lesbar — "
            "config_fallback (Start=%s, Dauer=%s h).",
            consumer.get("id"),
            fb_start,
            fb_duration,
        )
        return float(fb_start), float(fb_duration), "config_fallback", None

    logger.warning(
        "Verbraucher '%s': natives Filterfenster weder aus Loxone noch Fallback — "
        "keine Slot-Sperrung.",
        consumer.get("id"),
    )
    return None, None, "unbekannt", None


def resolve_filter_context(
    consumer: dict,
    matrix: list,
    logged_simulation: bool,
) -> dict:
    start, duration, source_label, log_extra = resolve_native_window(
        consumer, logged_simulation
    )
    if log_extra is not None and start is not None:
        logger.info(
            "Verbraucher '%s': natives Filterfenster Start=%.0f h (Format=%s, raw=%r).",
            consumer.get("id"),
            start,
            log_extra.get("format"),
            log_extra.get("raw"),
        )
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


def expected_native_delivery_kwh(consumer: dict, filter_context: dict | None) -> float:
    """Erwartete native Filterenergie (kWh) für gesperrte Slots im Horizont."""
    if not filter_context or not filter_schedule_enabled(consumer):
        return 0.0
    blocked = filter_context.get("blocked_indices") or []
    power = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    return len(blocked) * power


def ernie_filter_remaining_kwh(
    consumer: dict,
    debt_kwh: float,
    filter_context: dict | None,
) -> float:
    """Ernie-Zusatzziel: Loxone-Schulden minus erwartete native Lieferung im Horizont."""
    if debt_kwh <= 1e-9:
        return 0.0
    native_kwh = expected_native_delivery_kwh(consumer, filter_context)
    if native_kwh <= 1e-9:
        return debt_kwh
    ernie_kwh = max(0.0, debt_kwh - native_kwh)
    if ernie_kwh < debt_kwh - 1e-6:
        logger.info(
            "Verbraucher '%s': natives Fenster liefert ~%.2f kWh im Horizont — "
            "Ernie-Zusatzziel %.2f → %.2f kWh.",
            consumer.get("id"),
            native_kwh,
            debt_kwh,
            ernie_kwh,
        )
    return ernie_kwh


def adjust_targets_for_native_filter(
    targets: dict[str, float],
    consumers: list,
    optimization_matrix: list,
    filter_contexts: dict[str, dict] | None = None,
) -> dict[str, float]:
    """Reduziert Horizont-/Restziele um erwartete native Filterlieferung."""
    if not optimization_matrix:
        return targets
    contexts = filter_contexts or resolve_filter_contexts(optimization_matrix, consumers)
    adjusted = dict(targets)
    for consumer in consumers:
        if not filter_schedule_enabled(consumer):
            continue
        cid = consumer["id"]
        if cid not in adjusted:
            continue
        adjusted[cid] = ernie_filter_remaining_kwh(
            consumer, float(adjusted[cid]), contexts.get(cid)
        )
    return adjusted


def serialize_filter_contexts(contexts: dict[str, dict]) -> dict[str, dict]:
    """Schlanke, JSON-taugliche Fenster-Infos fürs Produktiv-Log (ohne Matrix-Indizes)."""
    serialized: dict[str, dict] = {}
    for cid, ctx in (contexts or {}).items():
        serialized[cid] = {
            "native_start_hour": ctx.get("native_start_hour"),
            "native_duration_hours": ctx.get("native_duration_hours"),
            "source_label": ctx.get("source_label"),
        }
    return serialized


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
