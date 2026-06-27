"""Ladesession-Zustand für Verbraucher mit Fertigstellungs-Deadline (über Mitternacht)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from .charging_context import charging_schedule_enabled


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


def purge_expired_sessions(sessions: dict[str, dict], now: dt.datetime) -> None:
    """Entfernt Sessions, deren Deadline erreicht oder überschritten ist."""
    for cid in list(sessions):
        deadline = _parse_deadline(sessions[cid].get("deadline"))
        if deadline is not None and now >= deadline:
            del sessions[cid]


def sync_charging_sessions(
    sessions: dict[str, dict],
    charging_contexts: dict[str, dict],
    consumers_by_id: dict[str, dict],
    now: dt.datetime,
) -> None:
    """Legt Sessions an oder aktualisiert Ziel/Deadline; entfernt abgelaufene."""
    purge_expired_sessions(sessions, now)
    for cid, ctx in charging_contexts.items():
        consumer = consumers_by_id.get(cid)
        if consumer is None or not is_charging_session_context(consumer, ctx):
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

    if charging_contexts:
        sync_charging_sessions(sessions, charging_contexts, consumers_by_id, current)
    else:
        purge_expired_sessions(sessions, current)

    delivered = dict(raw.get("delivered") or {})
    if not isinstance(delivered, dict):
        delivered = {}

    if raw.get("date") != today:
        delivered = {}

    return {
        "date": today,
        "delivered": delivered,
        "charging_sessions": sessions,
    }
