"""Konfigurierbare Loxone-Event-Trigger für außerplanmäßige Optimierung."""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable

from integrations import loxone_client

logger = logging.getLogger(__name__)

TRIGGER_QUARTER_HOUR = "quarter_hour"
TRIGGER_EVENT_PREFIX = "event:"

_BINARY_ON_CHANGE = frozenset({"any", "rising", "falling"})
_TEXT_ON_CHANGE = frozenset({"any"})


def build_run_trigger(trigger_id: str) -> str:
    return f"{TRIGGER_EVENT_PREFIX}{trigger_id}"


def is_event_trigger(run_trigger: str) -> bool:
    return run_trigger != TRIGGER_QUARTER_HOUR


def parse_binary_value(raw) -> bool | None:
    """Wandelt einen Loxone-Merker in True/False um; None bei Lesefehler."""
    if raw is None:
        return None
    try:
        return int(round(float(raw))) == 1
    except (TypeError, ValueError):
        return None


def parse_text_value(raw) -> str | None:
    """Normalisiert einen Loxone-Textwert; None bei Lesefehler."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text else None


def parse_analog_value(raw) -> float | None:
    """Wandelt einen Loxone-Messwert in float um; None bei Lesefehler."""
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return round(value, 2)


def fetch_trigger_snapshot(trigger_specs: list[dict]) -> dict[str, Any]:
    """Liest alle konfigurierten Trigger-Signale von Loxone."""
    snapshot: dict[str, Any] = {}
    for spec in trigger_specs:
        trigger_id = spec["id"]
        io_name = spec["loxone_name"]
        signal_type = spec["signal_type"]
        if signal_type == "text":
            snapshot[trigger_id] = parse_text_value(
                loxone_client.fetch_loxone_raw_value(io_name)
            )
        elif signal_type == "analog":
            snapshot[trigger_id] = parse_analog_value(
                loxone_client.fetch_loxone_generic_value(io_name)
            )
        else:
            snapshot[trigger_id] = parse_binary_value(
                loxone_client.fetch_loxone_generic_value(io_name)
            )
    return snapshot


def snapshot_from_run_state(state: dict | None) -> dict[str, Any]:
    """Extrahiert den zuletzt gespeicherten Trigger-Snapshot aus optimizer_run_state."""
    if not state:
        return {}
    raw = state.get("event_trigger_snapshot")
    if isinstance(raw, dict):
        return dict(raw)
    legacy = state.get("charging_plugged_in")
    if isinstance(legacy, dict):
        return {str(k): v for k, v in legacy.items()}
    return {}


def _binary_change_matches(previous: bool, current: bool, on_change: str) -> bool:
    if previous == current:
        return False
    if on_change == "any":
        return True
    if on_change == "rising":
        return current and not previous
    if on_change == "falling":
        return previous and not current
    return False


def _value_changed(previous: Any, current: Any, on_change: str) -> bool:
    if previous is None or current is None:
        return False
    if on_change != "any":
        return False
    return previous != current


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _format_change_detail(spec: dict, previous: Any, current: Any) -> str:
    label = spec.get("label") or spec["id"]
    return f"{label}: {previous!r} → {current!r}"


def detect_trigger_event(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    trigger_specs: list[dict],
) -> tuple[str | None, list[str]]:
    """Erkennt die erste relevante Änderung gemäß Trigger-Konfiguration."""
    if not previous or not trigger_specs:
        return None, []
    for spec in trigger_specs:
        trigger_id = spec["id"]
        prev = previous.get(trigger_id)
        cur = current.get(trigger_id)
        if spec["signal_type"] == "binary":
            if not isinstance(prev, bool) or not isinstance(cur, bool):
                continue
            if not _binary_change_matches(prev, cur, spec["on_change"]):
                continue
        elif spec["signal_type"] == "analog":
            if not _is_numeric(prev) or not _is_numeric(cur):
                continue
            if not _value_changed(float(prev), float(cur), spec["on_change"]):
                continue
        elif not _value_changed(prev, cur, spec["on_change"]):
            continue
        detail = _format_change_detail(spec, prev, cur)
        return build_run_trigger(trigger_id), [detail]
    return None, []


def wait_until_next_run(
    *,
    previous_snapshot: dict[str, Any],
    trigger_specs: list[dict],
    total_wait_sec: float,
    poll_interval_sec: int,
    event_trigger_enabled: bool,
    sleep_fn: Callable[[float], None] = time.sleep,
    fetch_snapshot_fn: Callable[[], dict[str, Any]] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Wartet bis zur nächsten Viertelstunde oder bis ein Event-Trigger feuert."""
    fetch = fetch_snapshot_fn or (lambda: fetch_trigger_snapshot(trigger_specs))
    known = dict(previous_snapshot)
    remaining = float(total_wait_sec)

    if remaining <= 0:
        return None, known

    if not event_trigger_enabled or not trigger_specs:
        sleep_fn(remaining)
        return None, known

    poll = max(1, int(poll_interval_sec))
    while remaining > 0:
        chunk = min(poll, remaining)
        sleep_fn(chunk)
        remaining -= chunk
        current = fetch()
        trigger, details = detect_trigger_event(known, current, trigger_specs)
        if trigger:
            logger.info(
                "Event-Trigger erkannt (%s) – Optimierung wird vorzeitig angestoßen.",
                "; ".join(details),
            )
            return trigger, current
        for trigger_id, value in current.items():
            if value is not None:
                known[trigger_id] = value
    return None, known
