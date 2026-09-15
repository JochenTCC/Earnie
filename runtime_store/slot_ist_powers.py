"""Resolve Produktiv-Log Ist powers: prefer closed_interval mean, else snapshot."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from data.live_consumption import is_dead_telemetry_snapshot
from optimizer.schedule import quarter_hour_slot_start
from runtime_store.power_interval_sampler import MIN_SAMPLE_COUNT_FOR_MEAN

IST_SOURCE_MEAN = "mean"
IST_SOURCE_DECISION = "decision"
IST_SOURCE_EMPTY = "empty"

_MEAN_KEYS = (
    "pv_kw",
    "grid_kw",
    "battery_kw",
    "house_kw",
    "baseload_kw",
    "flex_sum_kw",
    "flex_kw",
)


def slot_key(moment: datetime) -> datetime:
    """Normalize to naive quarter-hour start for closed_interval lookup."""
    naive = moment.replace(tzinfo=None) if moment.tzinfo is not None else moment
    return quarter_hour_slot_start(naive)


def _parse_interval_start(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return slot_key(moment)


def closed_interval_usable(closed: dict[str, Any] | None) -> bool:
    """True when slot-mean Ist should replace the decision-time snapshot."""
    if not closed or not isinstance(closed, dict):
        return False
    try:
        count = int(closed.get("sample_count") or 0)
    except (TypeError, ValueError):
        return False
    return count >= MIN_SAMPLE_COUNT_FOR_MEAN


def snapshot_from_closed_interval(closed: dict[str, Any]) -> dict[str, Any]:
    """Shape closed_interval means like ``consumption_snapshot`` for chart/Kosten."""
    return {key: closed[key] for key in _MEAN_KEYS if key in closed}


def index_closed_intervals_by_start(
    entries: list[dict[str, Any]],
) -> dict[datetime, dict[str, Any]]:
    """Map interval_start → closed_interval (later entries overwrite)."""
    indexed: dict[datetime, dict[str, Any]] = {}
    for entry in entries:
        closed = entry.get("closed_interval")
        if not isinstance(closed, dict):
            continue
        start = _parse_interval_start(closed.get("interval_start"))
        if start is None:
            continue
        indexed[start] = closed
    return indexed


def decision_snapshot(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not entry:
        return {}
    snapshot = entry.get("consumption_snapshot") or {}
    if is_dead_telemetry_snapshot(snapshot):
        return {}
    return dict(snapshot)


def resolve_ist_snapshot(
    slot_start: datetime,
    plan_entry: dict[str, Any] | None,
    closed_by_interval: dict[datetime, dict[str, Any]] | None,
) -> tuple[dict[str, Any], str]:
    """
    Ist powers for chart / Kosten / Soll–Ist.

    Prefer usable ``closed_interval`` for ``slot_start``; else decision snapshot
    on the plan entry (legacy / low sample_count).
    """
    closed = (closed_by_interval or {}).get(slot_key(slot_start))
    if closed_interval_usable(closed):
        return snapshot_from_closed_interval(closed or {}), IST_SOURCE_MEAN
    snap = decision_snapshot(plan_entry)
    if snap:
        return snap, IST_SOURCE_DECISION
    return {}, IST_SOURCE_EMPTY


def ist_mean_usable_for_slot(
    slot_start: datetime,
    closed_by_interval: dict[datetime, dict[str, Any]] | None,
) -> bool:
    closed = (closed_by_interval or {}).get(slot_key(slot_start))
    return closed_interval_usable(closed)
