"""Ladesession-Zustand für Verbraucher mit Fertigstellungs-Deadline (über Mitternacht)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from .charging_context import charging_schedule_enabled

SESSION_FULFILL_EPSILON_KWH = 0.05


def _parse_deadline(value: str | dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return dt.datetime.fromisoformat(text)


def deadline_reached(now: dt.datetime, deadline: dt.datetime) -> bool:
    """Compare now/deadline even if only one side is timezone-aware."""
    if now.tzinfo is None and deadline.tzinfo is not None:
        return now >= deadline.replace(tzinfo=None)
    if now.tzinfo is not None and deadline.tzinfo is None:
        return now.replace(tzinfo=None) >= deadline
    return now >= deadline


def is_charging_session_context(consumer: dict, ctx: dict | None) -> bool:
    """True wenn Ladeziel an eine Deadline gebunden ist (nicht Tageszähler)."""
    if not charging_schedule_enabled(consumer):
        return False
    if not ctx or not ctx.get("active", True):
        return False
    deadline = ctx.get("deadline")
    target = ctx.get("target_kwh")
    return isinstance(deadline, dt.datetime) and target is not None and float(target) > 0


def session_target_fulfilled(session: dict[str, Any] | None) -> bool:
    """True wenn gebuchte Energie das Session-Ziel (fast) erreicht hat."""
    if not session:
        return False
    target = float(session.get("target_kwh") or 0.0)
    if target <= SESSION_FULFILL_EPSILON_KWH:
        return False
    delivered = float(session.get("delivered_kwh") or 0.0)
    return delivered >= target - SESSION_FULFILL_EPSILON_KWH


def purge_expired_sessions(
    sessions: dict[str, dict],
    now: dt.datetime,
) -> set[str]:
    """Entfernt abgelaufene Sessions; liefert IDs die beim Purge erfüllt waren."""
    fulfilled_purged: set[str] = set()
    for cid in list(sessions):
        deadline = _parse_deadline(sessions[cid].get("deadline"))
        if deadline is not None and deadline_reached(now, deadline):
            if session_target_fulfilled(sessions[cid]):
                fulfilled_purged.add(cid)
            del sessions[cid]
    return fulfilled_purged


def sync_plug_cycle_fulfilled(
    fulfilled: dict[str, bool],
    charging_contexts: dict[str, dict],
    sessions: dict[str, dict],
    *,
    fulfilled_from_purge: set[str] | None = None,
) -> dict[str, bool]:
    """
    Latch: Ziel erreicht → erfüllt bis Unplug; Unplug löscht den Latch.
    Überlebt Deadline-Purge, solange das Auto angesteckt bleibt.
    """
    out = {cid: True for cid, flag in fulfilled.items() if flag}
    for cid in fulfilled_from_purge or ():
        out[cid] = True
    for cid, session in sessions.items():
        if session_target_fulfilled(session):
            out[cid] = True
    for cid, ctx in charging_contexts.items():
        if ctx.get("plugged_in") is False:
            out.pop(cid, None)
    return out


def _context_marks_cycle_complete(ctx: dict) -> bool:
    """True wenn angesteckt und Ladung für diesen Zyklus als erledigt gilt."""
    if ctx.get("plugged_in") is not True:
        return False
    if ctx.get("active", True):
        return False
    src = str(ctx.get("source_label") or "").lower()
    return "abgeschlossen" in src or "erfüllt" in src or "erfuellt" in src


def sync_open_charging_deadlines(
    open_deadlines: dict[str, str],
    charging_contexts: dict[str, dict],
    *,
    plug_cycle_fulfilled: dict[str, bool] | None = None,
    now: dt.datetime,
) -> dict[str, str]:
    """
    Latch: aktive Plug-Deadline bleibt über kurzes Unplug erhalten.

    Gesetzt solange angesteckt + aktiver Ladekontext mit Deadline.
    Gelöscht bei Deadline-Ablauf, Ziel erreicht oder Ladung abgeschlossen.
    Unplug allein löscht den Latch nicht (Kurzunterbrechung vor FertigUm).
    """
    fulfilled = plug_cycle_fulfilled or {}
    out: dict[str, str] = {}
    for cid, raw_dl in (open_deadlines or {}).items():
        if fulfilled.get(cid):
            continue
        deadline = _parse_deadline(raw_dl)
        if deadline is None or deadline_reached(now, deadline):
            continue
        out[str(cid)] = deadline.isoformat(timespec="seconds")

    for cid, ctx in charging_contexts.items():
        key = str(cid)
        if fulfilled.get(key):
            out.pop(key, None)
            continue
        if _context_marks_cycle_complete(ctx):
            out.pop(key, None)
            continue
        if ctx.get("plugged_in") is not True or not ctx.get("active", True):
            continue
        deadline = ctx.get("deadline")
        if not isinstance(deadline, dt.datetime) or deadline_reached(now, deadline):
            continue
        out[key] = deadline.isoformat(timespec="seconds")
    return out


def parse_open_charging_deadline(
    open_deadlines: dict[str, str] | None,
    consumer_id: str,
) -> dt.datetime | None:
    if not open_deadlines:
        return None
    return _parse_deadline(open_deadlines.get(str(consumer_id)))


def sync_charging_sessions(
    sessions: dict[str, dict],
    charging_contexts: dict[str, dict],
    consumers_by_id: dict[str, dict],
    now: dt.datetime,
    *,
    plug_cycle_fulfilled: dict[str, bool] | None = None,
) -> set[str]:
    """Legt Sessions an oder aktualisiert Ziel/Deadline; entfernt abgelaufene."""
    fulfilled_from_purge = purge_expired_sessions(sessions, now)
    latched = {
        cid
        for cid, flag in (plug_cycle_fulfilled or {}).items()
        if flag
    } | set(fulfilled_from_purge)
    for cid, ctx in charging_contexts.items():
        consumer = consumers_by_id.get(cid)
        if consumer is None or not is_charging_session_context(consumer, ctx):
            continue
        if cid in latched and ctx.get("plugged_in") is True:
            continue
        deadline = ctx["deadline"]
        target = round(float(ctx["target_kwh"]), 3)
        dl_iso = deadline.isoformat(timespec="seconds")
        if cid in sessions:
            prev = float(sessions[cid].get("target_kwh") or 0.0)
            if target > prev:
                sessions[cid]["target_kwh"] = target
            sessions[cid]["deadline"] = dl_iso
        else:
            sessions[cid] = {
                "target_kwh": target,
                "delivered_kwh": 0.0,
                "deadline": dl_iso,
            }
    return fulfilled_from_purge


def charging_session_remaining_kwh(
    ctx: dict | None,
    *,
    daily_target: float,
    delivered_kwh: float,
) -> float:
    """Energy still needed for MILP.

    Plugged-in ctx.target_kwh is already Ist-SOC remaining. Subtracting booked
    delivery again double-counts the same energy (dump 20260813_075350).
    """
    target = max(0.0, float(daily_target))
    if (ctx or {}).get("plugged_in") is True:
        return target
    return max(0.0, target - float(delivered_kwh))


def session_delivered_kwh(sessions: dict[str, dict], consumer_id: str) -> float:
    session = sessions.get(consumer_id)
    if not session:
        return 0.0
    return float(session.get("delivered_kwh", 0.0) or 0.0)


def add_session_delivery(
    sessions: dict[str, dict],
    consumer_id: str,
    delta_kwh: float,
) -> None:
    session = sessions.get(consumer_id)
    if not session or delta_kwh <= 0:
        return
    session["delivered_kwh"] = round(
        float(session.get("delivered_kwh", 0.0) or 0.0) + delta_kwh,
        3,
    )


def normalize_consumer_state(
    raw: dict[str, Any],
    today: str,
    charging_contexts: dict[str, dict] | None,
    consumers_by_id: dict[str, dict],
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """
    Tägliche delivered-Werte nur für Nicht-Session-Verbraucher zurücksetzen.
    charging_sessions bleiben bis zur Deadline erhalten.
    """
    current = now or dt.datetime.now()
    sessions = dict(raw.get("charging_sessions") or {})
    if not isinstance(sessions, dict):
        sessions = {}

    fulfilled_raw = dict(raw.get("plug_cycle_fulfilled") or {})
    if not isinstance(fulfilled_raw, dict):
        fulfilled_raw = {}
    fulfilled = {str(cid): True for cid, flag in fulfilled_raw.items() if flag}

    open_raw = dict(raw.get("open_charging_deadlines") or {})
    if not isinstance(open_raw, dict):
        open_raw = {}
    open_deadlines = {
        str(cid): str(dl)
        for cid, dl in open_raw.items()
        if dl is not None and str(dl).strip()
    }

    if charging_contexts:
        purged_fulfilled = sync_charging_sessions(
            sessions,
            charging_contexts,
            consumers_by_id,
            current,
            plug_cycle_fulfilled=fulfilled,
        )
        fulfilled = sync_plug_cycle_fulfilled(
            fulfilled,
            charging_contexts,
            sessions,
            fulfilled_from_purge=purged_fulfilled,
        )
        open_deadlines = sync_open_charging_deadlines(
            open_deadlines,
            charging_contexts,
            plug_cycle_fulfilled=fulfilled,
            now=current,
        )
    else:
        purged_fulfilled = purge_expired_sessions(sessions, current)
        for cid in purged_fulfilled:
            fulfilled[cid] = True
        open_deadlines = sync_open_charging_deadlines(
            open_deadlines,
            {},
            plug_cycle_fulfilled=fulfilled,
            now=current,
        )

    delivered = dict(raw.get("delivered") or {})
    if not isinstance(delivered, dict):
        delivered = {}

    if raw.get("date") != today:
        delivered = {}

    generic_flex_run = dict(raw.get("generic_flex_run") or {})
    if not isinstance(generic_flex_run, dict):
        generic_flex_run = {}
    if raw.get("date") != today:
        generic_flex_run = {}

    return {
        "date": today,
        "delivered": delivered,
        "charging_sessions": sessions,
        "generic_flex_run": generic_flex_run,
        "plug_cycle_fulfilled": fulfilled,
        "open_charging_deadlines": open_deadlines,
    }
