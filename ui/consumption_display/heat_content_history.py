"""Load Live heat content (Q_sim / Q_meas) from optimization_history.jsonl."""
from __future__ import annotations

from dataclasses import dataclass
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


def _as_naive(moment: datetime) -> datetime:
    """Strip tzinfo so Analyse (aware) windows compare to JSONL (naive) stamps."""
    return moment.replace(tzinfo=None) if moment.tzinfo is not None else moment


def _hour_key(moment: datetime) -> datetime:
    return _as_naive(moment).replace(minute=0, second=0, microsecond=0)


def _q_from_observability_item(
    item: dict[str, Any], field: str
) -> float | None:
    hc = item.get("heat_content_kwh") or {}
    raw = hc.get(field)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _series_key_for_item(item: dict[str, Any]) -> str | None:
    kind = str(item.get("kind") or "")
    cid = str(item.get("consumer_id") or "")
    if kind == "heat_storage" or (
        not kind and "temp_eq" in (item.get("readings_c") or {})
    ):
        return HC_HEAT_STORAGE
    if cid:
        return f"pool_q_{cid}"
    return None


def _label_for_key(key: str) -> str:
    if key == HC_HEAT_STORAGE:
        return "Wärmespeicher"
    if key.startswith("pool_q_"):
        return key[len("pool_q_") :]
    return key


def _extract_q_by_series_key(
    entry: dict[str, Any], field: str
) -> dict[str, float]:
    """Map heat_content series keys → Q value from one history entry."""
    out: dict[str, float] = {}
    for item in entry.get("thermal_observability") or []:
        if not isinstance(item, dict) or item.get("error"):
            continue
        value = _q_from_observability_item(item, field)
        if value is None:
            continue
        key = _series_key_for_item(item)
        if key is None:
            continue
        out[key] = value
    return out


def _load_entries_by_hour(
    window_start: datetime, window_end_inclusive: datetime
) -> dict[datetime, dict[str, dict[str, float]]]:
    """Hour → series_key → {q_sim?, q_meas?} (last entry in hour wins).

    ``window_end_inclusive`` is inclusive; the JSONL loader uses ``[start, end)``.
    """
    from runtime_store import optimization_history

    start = _as_naive(window_start)
    end = _as_naive(window_end_inclusive)
    try:
        entries = optimization_history.load_replay_entries_between(
            start, end + timedelta(microseconds=1)
        )
    except Exception:
        return {}

    by_hour: dict[datetime, dict[str, dict[str, float]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        completed = _parse_ts(str(entry.get("completed_at") or ""))
        if completed is None:
            continue
        completed = _as_naive(completed)
        if completed < start or completed > end:
            continue
        hour = _hour_key(completed)
        bucket = by_hour.setdefault(hour, {})
        for field in ("q_sim", "q_meas"):
            for key, value in _extract_q_by_series_key(entry, field).items():
                bucket.setdefault(key, {})[field] = value
    return by_hour


def _hourly_grid(window_start: datetime, window_end: datetime) -> list[datetime]:
    hour = _hour_key(window_start)
    end_hour = _hour_key(window_end)
    out: list[datetime] = []
    while hour <= end_hour:
        out.append(hour)
        hour += timedelta(hours=1)
    return out


@dataclass(frozen=True)
class LiveHeatContentSeries:
    """Aligned hourly Live Q_sim / Q_meas series for one Analyse window."""

    timestamps: list[str]
    q_sim_by_key: dict[str, list[float | None]]
    q_meas_by_key: dict[str, list[float | None]]
    labels: dict[str, str]

    def has_any_values(self) -> bool:
        for series in (*self.q_sim_by_key.values(), *self.q_meas_by_key.values()):
            if any(v is not None for v in series):
                return True
        return False


def live_heat_content_for_window(
    window_start: datetime,
    window_end: datetime,
) -> LiveHeatContentSeries | None:
    """Discover series keys from Live history and align Q_sim/Q_meas to hours."""
    by_hour = _load_entries_by_hour(window_start, window_end)
    if not by_hour:
        return None

    keys: list[str] = []
    seen: set[str] = set()
    for bucket in by_hour.values():
        for key in bucket:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    if not keys:
        return None

    hours = _hourly_grid(window_start, window_end)
    timestamps = [h.strftime("%Y-%m-%d %H:%M:%S") for h in hours]
    q_sim: dict[str, list[float | None]] = {key: [] for key in keys}
    q_meas: dict[str, list[float | None]] = {key: [] for key in keys}
    for hour in hours:
        bucket = by_hour.get(hour) or {}
        for key in keys:
            values = bucket.get(key) or {}
            q_sim[key].append(values.get("q_sim"))
            q_meas[key].append(values.get("q_meas"))

    result = LiveHeatContentSeries(
        timestamps=timestamps,
        q_sim_by_key=q_sim,
        q_meas_by_key=q_meas,
        labels={key: _label_for_key(key) for key in keys},
    )
    if not result.has_any_values():
        return None
    return result


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

    window_start = _hour_key(min(valid))
    # Inclusive end of the last hour so :15/:45 samples still map into that hour.
    window_end = _hour_key(max(valid)) + timedelta(hours=1) - timedelta(microseconds=1)
    by_hour = _load_entries_by_hour(window_start, window_end)

    result: dict[str, list[float | None]] = {key: [] for key in keys}
    for moment in moments:
        hour = _hour_key(moment) if moment is not None else None
        bucket = by_hour.get(hour) if hour is not None else None
        for key in keys:
            if bucket is None:
                result[key].append(None)
            else:
                values = bucket.get(key) or {}
                result[key].append(values.get("q_meas"))
    return result
