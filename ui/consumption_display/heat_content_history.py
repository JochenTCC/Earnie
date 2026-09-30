"""Load measured heat content (Q_meas) from Live optimization_history.jsonl."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from data.modeled_temperatures import HC_HEAT_STORAGE


def _parse_ts(value: str) -> datetime | None:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _hour_key(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _q_meas_from_observability_item(item: dict[str, Any]) -> float | None:
    hc = item.get("heat_content_kwh") or {}
    raw = hc.get("q_meas")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _extract_q_meas_by_series_key(entry: dict[str, Any]) -> dict[str, float]:
    """Map heat_content series keys → Q_meas from one history entry."""
    out: dict[str, float] = {}
    for item in entry.get("thermal_observability") or []:
        if not isinstance(item, dict) or item.get("error"):
            continue
        q_meas = _q_meas_from_observability_item(item)
        if q_meas is None:
            continue
        kind = str(item.get("kind") or "")
        cid = str(item.get("consumer_id") or "")
        if kind == "heat_storage" or (
            not kind and "temp_eq" in (item.get("readings_c") or {})
        ):
            out[HC_HEAT_STORAGE] = q_meas
            continue
        if cid:
            out[f"pool_q_{cid}"] = q_meas
    return out


def measured_heat_content_for_timestamps(
    timestamps: list[str],
    *,
    series_keys: list[str] | None = None,
) -> dict[str, list[float | None]]:
    """Align Live Q_meas to hourly chart timestamps (last value per hour; gaps = None)."""
    keys = list(series_keys or [])
    empty = {key: [None] * len(timestamps) for key in keys}
    if not timestamps or not keys:
        return empty

    moments = [_parse_ts(ts) for ts in timestamps]
    valid = [m for m in moments if m is not None]
    if not valid:
        return empty

    from runtime_store import optimization_history

    window_start = _hour_key(min(valid))
    window_end = _hour_key(max(valid)) + timedelta(hours=1)
    try:
        entries = optimization_history.load_replay_entries_between(
            window_start, window_end
        )
    except Exception:
        return empty

    by_hour: dict[datetime, dict[str, float]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        completed = _parse_ts(str(entry.get("completed_at") or ""))
        if completed is None:
            continue
        values = _extract_q_meas_by_series_key(entry)
        if not values:
            continue
        hour = _hour_key(completed)
        bucket = by_hour.setdefault(hour, {})
        bucket.update(values)

    result: dict[str, list[float | None]] = {key: [] for key in keys}
    for moment in moments:
        hour = _hour_key(moment) if moment is not None else None
        bucket = by_hour.get(hour) if hour is not None else None
        for key in keys:
            if bucket is None:
                result[key].append(None)
            else:
                result[key].append(bucket.get(key))
    return result
