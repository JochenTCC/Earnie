"""Disk cache for research EU power/weather forecast frames (cross-process)."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from runtime_store.persist_paths import runtime_path

KIND_POWER = "eu_power_forecast"
KIND_WEATHER = "eu_weather_forecast"
STATUS_FILENAME = "eu_forecast_cache_status.json"
DEFAULT_TTL_SEC = 45 * 60

STATE_MISSING = "missing"
STATE_WARMING = "warming"
STATE_READY = "ready"
STATE_STALE = "stale"
STATE_ERROR = "error"
STATE_INACTIVE = "inactive"

logger = logging.getLogger(__name__)


def cache_dir() -> Path:
    path = Path(runtime_path("cache"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def frame_path(kind: str, start: date, end: date) -> Path:
    return cache_dir() / f"{kind}_{start.isoformat()}_{end.isoformat()}.json"


def status_path() -> Path:
    return cache_dir() / STATUS_FILENAME


def _frame_to_payload(frame: pd.DataFrame, start: date, end: date, fetched_at: float) -> dict[str, Any]:
    index_iso = [pd.Timestamp(ts).isoformat() for ts in frame.index]
    columns = {
        str(col): [None if pd.isna(v) else float(v) for v in frame[col].tolist()]
        for col in frame.columns
    }
    return {
        "fetched_at": float(fetched_at),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "index": index_iso,
        "columns": columns,
    }


def _payload_to_frame(payload: dict[str, Any]) -> pd.DataFrame:
    index = pd.DatetimeIndex([datetime.fromisoformat(ts) for ts in payload["index"]])
    columns = payload.get("columns") or {}
    frame = pd.DataFrame(
        {name: values for name, values in columns.items()},
        index=index,
    )
    return frame.sort_index()


def save_frame(kind: str, start: date, end: date, frame: pd.DataFrame) -> Path:
    """Atomic JSON write under runtime/cache."""
    if frame is None or frame.empty:
        raise ValueError("save_frame: leeres DataFrame.")
    fetched_at = time.time()
    path = frame_path(kind, start, end)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = _frame_to_payload(frame, start, end, fetched_at)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_frame(
    kind: str,
    start: date,
    end: date,
    ttl_sec: float = DEFAULT_TTL_SEC,
) -> tuple[pd.DataFrame | None, float | None, bool]:
    """Return (frame|None, age_sec|None, is_fresh).

    Stale-but-present frames are returned with ``is_fresh=False``.
    """
    path = frame_path(kind, start, end)
    if not path.is_file():
        return None, None, False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        logger.warning("EU-Forecast-Disk-Cache unlesbar (%s): %s", path.name, exc)
        return None, None, False
    if not isinstance(payload, dict):
        return None, None, False
    fetched_at = float(payload.get("fetched_at") or 0.0)
    if fetched_at <= 0:
        return None, None, False
    age = time.time() - fetched_at
    try:
        frame = _payload_to_frame(payload)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("EU-Forecast-Disk-Cache ungültig (%s): %s", path.name, exc)
        return None, None, False
    if frame.empty:
        return None, age, False
    return frame, age, age <= float(ttl_sec)


def write_status(fields: dict[str, Any]) -> None:
    """Merge/overwrite status sidecar for Streamlit / ops."""
    path = status_path()
    current: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except (OSError, json.JSONDecodeError, UnicodeError):
            current = {}
    current.update(fields)
    current["updated_at"] = time.time()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_status() -> dict[str, Any]:
    path = status_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def inspect_kind_freshness(
    kind: str,
    start: date | None,
    end: date | None,
    ttl_sec: float = DEFAULT_TTL_SEC,
) -> tuple[bool, float | None, bool]:
    """Return (present, age_sec|None, is_fresh) without loading full frame into callers."""
    if start is None or end is None:
        return False, None, False
    _frame, age, fresh = load_frame(kind, start, end, ttl_sec=ttl_sec)
    return _frame is not None, age, fresh


def refresh_status_from_disk(
    start: date,
    end: date,
    *,
    ttl_sec: float = DEFAULT_TTL_SEC,
    eu_power_live_source: str = "energy_charts_forecast",
    missing_price_strategy: str | None = None,
    live_bias_enabled: bool | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Recompute sidecar from disk frames after fetch/save."""
    power_present, power_age, power_fresh = inspect_kind_freshness(
        KIND_POWER, start, end, ttl_sec=ttl_sec
    )
    weather_present, weather_age, weather_fresh = inspect_kind_freshness(
        KIND_WEATHER, start, end, ttl_sec=ttl_sec
    )
    ages = [a for a in (power_age, weather_age) if a is not None]
    fetched_at = time.time() - max(ages) if ages else None
    if error:
        state = STATE_ERROR
    elif power_fresh and weather_fresh:
        state = STATE_READY
    elif power_present or weather_present:
        state = STATE_STALE
    else:
        side = read_status()
        state = STATE_WARMING if side.get("state") == STATE_WARMING else STATE_MISSING
    fields: dict[str, Any] = {
        "state": state,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "eu_power_live_source": eu_power_live_source,
        "power_fresh": power_fresh,
        "weather_fresh": weather_fresh,
        "ttl_sec": float(ttl_sec),
        "fetched_at": fetched_at,
        "error": error,
    }
    if missing_price_strategy is not None:
        fields["missing_price_strategy"] = missing_price_strategy
    if live_bias_enabled is not None:
        fields["live_bias_enabled"] = live_bias_enabled
    write_status(fields)
    return fields


def mark_warming(
    start: date,
    end: date,
    *,
    eu_power_live_source: str = "energy_charts_forecast",
    missing_price_strategy: str | None = None,
    live_bias_enabled: bool | None = None,
) -> None:
    fields: dict[str, Any] = {
        "state": STATE_WARMING,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "eu_power_live_source": eu_power_live_source,
        "error": None,
    }
    if missing_price_strategy is not None:
        fields["missing_price_strategy"] = missing_price_strategy
    if live_bias_enabled is not None:
        fields["live_bias_enabled"] = live_bias_enabled
    write_status(fields)


def get_eu_forecast_cache_status(
    *,
    ttl_sec: float = DEFAULT_TTL_SEC,
    eu_power_live_source: str | None = None,
    missing_price_strategy: str | None = None,
    live_bias_enabled: bool | None = None,
) -> dict[str, Any]:
    """Cross-process status for Optimierer-Dienst (no HTTP)."""
    sidecar = read_status()
    source = eu_power_live_source
    if source is None:
        source = str(sidecar.get("eu_power_live_source") or "archive_hod")
    strategy = missing_price_strategy
    if strategy is None:
        strategy = str(sidecar.get("missing_price_strategy") or "forecast")
    bias = live_bias_enabled
    if bias is None:
        bias = bool(sidecar.get("live_bias_enabled", False))

    status: dict[str, Any] = {
        "eu_power_live_source": source,
        "missing_price_strategy": strategy,
        "live_bias_enabled": bias,
        "ttl_sec": float(ttl_sec),
        "state": STATE_INACTIVE,
        "fetched_at": sidecar.get("fetched_at"),
        "age_sec": None,
        "range_start": sidecar.get("range_start"),
        "range_end": sidecar.get("range_end"),
        "power_fresh": False,
        "weather_fresh": False,
        "error": sidecar.get("error"),
        "updated_at": sidecar.get("updated_at"),
    }

    if source != "energy_charts_forecast":
        status["state"] = STATE_INACTIVE
        return status

    range_start = sidecar.get("range_start")
    range_end = sidecar.get("range_end")
    start_d: date | None = None
    end_d: date | None = None
    try:
        if range_start and range_end:
            start_d = date.fromisoformat(str(range_start))
            end_d = date.fromisoformat(str(range_end))
    except ValueError:
        start_d = None
        end_d = None

    power_present, power_age, power_fresh = inspect_kind_freshness(
        KIND_POWER, start_d, end_d, ttl_sec=ttl_sec
    )
    weather_present, weather_age, weather_fresh = inspect_kind_freshness(
        KIND_WEATHER, start_d, end_d, ttl_sec=ttl_sec
    )
    status["power_fresh"] = power_fresh
    status["weather_fresh"] = weather_fresh
    ages = [a for a in (power_age, weather_age) if a is not None]
    if ages:
        status["age_sec"] = max(ages)
    if sidecar.get("fetched_at") is not None:
        status["fetched_at"] = sidecar.get("fetched_at")
        status["age_sec"] = time.time() - float(sidecar["fetched_at"])

    side_state = str(sidecar.get("state") or "")
    if power_fresh and weather_fresh:
        status["state"] = STATE_READY
        return status
    if side_state == STATE_WARMING:
        status["state"] = STATE_WARMING
        return status
    if side_state == STATE_ERROR and not power_present and not weather_present:
        status["state"] = STATE_ERROR
        return status
    if not power_present and not weather_present:
        status["state"] = STATE_MISSING
        return status
    if power_present or weather_present:
        status["state"] = STATE_STALE
        return status
    status["state"] = STATE_MISSING
    return status
