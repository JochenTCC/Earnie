"""Durable day-ahead price cache for Live (QH; ENTSO-E / Energy-Charts)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from data.market_prices import normalize_price_slot
from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

CACHE_VERSION = 2
_CACHE_PREFIX = "live_day_ahead_"


def cache_path_for_zone(zone: str) -> Path:
    safe = str(zone).strip().replace("/", "-").replace("\\", "-") or "AT"
    return Path(runtime_path(f"{_CACHE_PREFIX}{safe}.json"))


def _parse_ts(raw: str, *, fallback_tz) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None and fallback_tz is not None:
        moment = moment.replace(tzinfo=fallback_tz)
    return normalize_price_slot(moment)


def _series_bounds(
    prices: list[dict[str, Any]],
    *,
    fallback_tz,
) -> tuple[datetime, datetime] | None:
    slots: list[datetime] = []
    for item in prices:
        slot = _parse_ts(item.get("timestamp"), fallback_tz=fallback_tz)
        if slot is not None:
            slots.append(slot)
    if not slots:
        return None
    return min(slots), max(slots)


def cache_covers_window(
    prices: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    *,
    fallback_tz=None,
) -> bool:
    """True when cached series spans [window_start, window_end] inclusive."""
    bounds = _series_bounds(prices, fallback_tz=fallback_tz)
    if bounds is None:
        return False
    first, last = bounds
    start = normalize_price_slot(window_start)
    end = normalize_price_slot(window_end)
    return first <= start and last >= end


def cache_is_fresh_for_day_ahead(
    fetched_at: datetime,
    now: datetime,
) -> bool:
    """Fresh if last fetch already includes today's Day-Ahead publish state."""
    from data.backtesting_prices import last_day_ahead_calendar_date

    return last_day_ahead_calendar_date(fetched_at) >= last_day_ahead_calendar_date(
        now
    )


def load_live_price_cache(
    zone: str,
    *,
    fallback_tz=None,
) -> dict[str, Any] | None:
    path = cache_path_for_zone(zone)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Ignoring unreadable day-ahead price cache %s", path)
        return None
    if not isinstance(raw, dict) or int(raw.get("version") or 0) != CACHE_VERSION:
        return None
    if str(raw.get("zone") or "") != str(zone):
        return None
    prices = raw.get("prices")
    if not isinstance(prices, list) or not prices:
        return None
    fetched_raw = raw.get("fetched_at")
    fetched_at = _parse_ts(fetched_raw, fallback_tz=fallback_tz)
    if fetched_at is None:
        return None
    source = str(raw.get("source") or "").strip() or None
    return {
        "zone": zone,
        "fetched_at": fetched_at,
        "prices": prices,
        "path": path,
        "source": source,
    }


def save_live_price_cache(
    zone: str,
    live_prices: list[dict[str, Any]],
    *,
    fetched_at: datetime,
    window_start: datetime,
    window_end: datetime,
    source: str | None = None,
) -> Path | None:
    """Persist QH series after a successful day-ahead network fetch."""
    if not live_prices:
        return None
    path = cache_path_for_zone(zone)
    payload: dict[str, Any] = {
        "version": CACHE_VERSION,
        "zone": zone,
        "fetched_at": fetched_at.isoformat(),
        "window_start": normalize_price_slot(window_start).isoformat(),
        "window_end": normalize_price_slot(window_end).isoformat(),
        "prices": [
            {
                "timestamp": item["timestamp"].isoformat(),
                "price_buy": float(item["price_buy"]),
            }
            for item in live_prices
            if item.get("timestamp") is not None
        ],
    }
    if source:
        payload["source"] = str(source)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("Could not write day-ahead price cache %s: %s", path, exc)
        return None
    return path


def cached_prices_to_live(
    prices: list[dict[str, Any]],
    *,
    fallback_tz,
) -> list[dict[str, Any]]:
    """Deserialize cache rows into Live market_data dicts."""
    live: list[dict[str, Any]] = []
    for item in prices:
        slot = _parse_ts(item.get("timestamp"), fallback_tz=fallback_tz)
        if slot is None:
            continue
        try:
            price = float(item["price_buy"])
        except (KeyError, TypeError, ValueError):
            continue
        live.append(
            {
                "timestamp": slot,
                "hour": slot.hour,
                "price_buy": round(price, 4),
            }
        )
    live.sort(key=lambda row: row["timestamp"])
    return live


def live_series_covers_window(
    live_prices: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> bool:
    if not live_prices:
        return False
    start = normalize_price_slot(window_start)
    end = normalize_price_slot(window_end)
    return (
        live_prices[0]["timestamp"] <= start
        and live_prices[-1]["timestamp"] >= end
    )


def merge_live_price_series(
    base: list[dict[str, Any]],
    overlay: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge QH rows; overlay wins on duplicate timestamps."""
    by_slot: dict[datetime, dict[str, Any]] = {
        row["timestamp"]: row for row in base if row.get("timestamp") is not None
    }
    for row in overlay:
        slot = row.get("timestamp")
        if slot is None:
            continue
        by_slot[slot] = row
    return sorted(by_slot.values(), key=lambda row: row["timestamp"])


def trim_live_price_series(
    live_prices: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    start = normalize_price_slot(window_start)
    end = normalize_price_slot(window_end)
    return [
        row
        for row in live_prices
        if start <= row["timestamp"] <= end
    ]


def network_fetch_start(
    needed_start: datetime,
    needed_end: datetime,
    cached_live: list[dict[str, Any]] | None,
    now: datetime,
) -> datetime:
    """
    Earliest network request start for day-ahead prices.

    When cache already holds the mirror lookback before today, request only
    from local midnight today through ``needed_end`` (history filled from cache).
    """
    del needed_end  # end always requested; only the history start is shortened
    needed_start = normalize_price_slot(needed_start)
    today = normalize_price_slot(now).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if today <= needed_start or not cached_live:
        return needed_start
    history_end = today - timedelta(minutes=15)
    if history_end < needed_start:
        return needed_start
    if live_series_covers_window(cached_live, needed_start, history_end):
        return today
    return needed_start
