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
        if deadline is not None and now >= deadline:
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
            sessions[cid]["target_kwh"] = target
            sessions[cid]["deadline"] = dl_iso
        else:
            sessions[cid] = {
                "target_kwh": target,
                "delivered_kwh": 0.0,
                "deadline": dl_iso,
            }
    return fulfilled_from_purge


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
    else:
        purged_fulfilled = purge_expired_sessions(sessions, current)
        for cid in purged_fulfilled:
            fulfilled[cid] = True

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
    }
