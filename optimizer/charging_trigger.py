"""Erkennung von An-/Absteck-Ereignissen für außerplanmäßige Optimierung."""
from __future__ import annotations

import logging
import time
from typing import Callable

import config
from integrations import loxone_client
from optimizer.charging_context import charging_schedule_enabled

logger = logging.getLogger(__name__)

TRIGGER_QUARTER_HOUR = "quarter_hour"
TRIGGER_PLUGGED_IN = "ev_plugged_in"
TRIGGER_UNPLUGGED = "ev_unplugged"


def parse_plugged_in_value(raw) -> bool | None:
    """Wandelt einen Loxone-Merker in angeschlossen (True/False) um; None bei Lesefehler."""
    if raw is None:
        return None
    try:
        return int(round(float(raw))) == 1
    except (TypeError, ValueError):
        return None


def consumers_with_plugged_in_signal() -> list[dict]:
    """Flexible Verbraucher mit Loxone-plugged_in_name und aktivem charging_schedule."""
    result: list[dict] = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        if consumer.get("daily_target_source") != "loxone":
            continue
        if not charging_schedule_enabled(consumer):
            continue
        lox = (consumer.get("charging_schedule") or {}).get("loxone") or {}
        if not lox.get("plugged_in_name"):
            continue
        result.append(consumer)
    return result


def fetch_plugged_in_snapshot() -> dict[str, bool | None]:
    """Liest den Anschlussstatus aller überwachten Verbraucher von Loxone."""
    snapshot: dict[str, bool | None] = {}
    for consumer in consumers_with_plugged_in_signal():
        cid = consumer["id"]
        lox = consumer["charging_schedule"]["loxone"]
        raw = loxone_client.fetch_loxone_generic_value(lox["plugged_in_name"])
        snapshot[cid] = parse_plugged_in_value(raw)
    return snapshot


def plugged_in_from_run_state(state: dict | None) -> dict[str, bool | None]:
    """Extrahiert den zuletzt gespeicherten Anschlussstatus aus optimizer_run_state."""
    if not state:
        return {}
    raw = state.get("charging_plugged_in")
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, bool | None] = {}
    for key, value in raw.items():
        if value is None:
            parsed[str(key)] = None
        else:
            parsed[str(key)] = bool(value)
    return parsed


def is_event_trigger(run_trigger: str) -> bool:
    return run_trigger != TRIGGER_QUARTER_HOUR


def detect_plugged_in_event(
    previous: dict[str, bool | None] | None,
    current: dict[str, bool | None],
) -> tuple[str | None, list[str]]:
    """
    Erkennt relevante Zustandswechsel (0→1 oder 1→0).

    Rückgabe: (trigger_code, detailzeilen) – trigger_code z. B. ev_plugged_in:eauto
    """
    if not previous:
        return None, []
    details: list[str] = []
    for cid, cur in current.items():
        prev = previous.get(cid)
        if prev is None or cur is None:
            continue
        if prev == cur:
            continue
        if cur and not prev:
            details.append(f"{cid}: nicht angeschlossen → angeschlossen")
            return f"{TRIGGER_PLUGGED_IN}:{cid}", details
        if prev and not cur:
            details.append(f"{cid}: angeschlossen → nicht angeschlossen")
            return f"{TRIGGER_UNPLUGGED}:{cid}", details
    return None, details


def wait_until_next_run(
    *,
    previous_plugged_in: dict[str, bool | None],
    total_wait_sec: float,
    poll_interval_sec: int,
    event_trigger_enabled: bool,
    sleep_fn: Callable[[float], None] = time.sleep,
    fetch_snapshot_fn: Callable[[], dict[str, bool | None]] | None = None,
) -> tuple[str | None, dict[str, bool | None]]:
    """
    Wartet bis zur nächsten Viertelstunde oder bis ein Lade-Event erkannt wird.

    Rückgabe: (event_trigger oder None, aktueller Snapshot)
    """
    fetch = fetch_snapshot_fn or fetch_plugged_in_snapshot
    known = dict(previous_plugged_in)
    remaining = float(total_wait_sec)

    if remaining <= 0:
        return None, known

    if not event_trigger_enabled or not consumers_with_plugged_in_signal():
        sleep_fn(remaining)
        return None, known

    poll = max(1, int(poll_interval_sec))
    while remaining > 0:
        chunk = min(poll, remaining)
        sleep_fn(chunk)
        remaining -= chunk
        current = fetch()
        trigger, details = detect_plugged_in_event(known, current)
        if trigger:
            logger.info(
                "Lade-Event erkannt (%s) – Optimierung wird vorzeitig angestoßen.",
                "; ".join(details),
            )
            return trigger, current
        for cid, value in current.items():
            if value is not None:
                known[cid] = value
    return None, known
