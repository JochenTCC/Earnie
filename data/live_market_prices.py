"""Live Day-Ahead prices: Energy-Charts first, disk cache, aWATTar hourly fallback."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import config
from data.data_loader import (
    MARKET_ZONE_AT,
    MARKET_ZONE_CH,
    fetch_energy_charts_prices,
)
from data.live_price_cache import (
    cache_covers_window,
    cache_is_fresh_for_day_ahead,
    cached_prices_to_live,
    load_live_price_cache,
    merge_live_price_series,
    network_fetch_start,
    save_live_price_cache,
    trim_live_price_series,
)
from data.market_prices import awattar_fetch_window, normalize_price_slot
from data.tariff_pricing import market_zone_for_land
from optimizer.slot_duration import normalize_quarter_hour_slot

logger = logging.getLogger(__name__)


def _runtime_market_zone() -> str:
    resolved = config.get_resolved_runtime_settings() or {}
    profile = resolved.get("_house_profile") or {}
    land = str(profile.get("land") or resolved.get("land") or "AT")
    try:
        return market_zone_for_land(land)
    except ValueError:
        logger.warning("Unknown land %r for live prices; using AT", land)
        return MARKET_ZONE_AT


def _planning_tz() -> ZoneInfo:
    return ZoneInfo(config.get_planning_timezone())


def _now_slot(planning_end: datetime | None) -> datetime:
    tz = planning_end.tzinfo if planning_end is not None else _planning_tz()
    return normalize_quarter_hour_slot(datetime.now(tz))


def _dataframe_to_live_market_data(df: pd.DataFrame) -> list[dict[str, Any]]:
    planning_tz = _planning_tz()
    prices: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        moment = pd.Timestamp(ts).to_pydatetime()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=planning_tz)
        else:
            moment = moment.astimezone(planning_tz)
        slot = normalize_price_slot(moment)
        prices.append(
            {
                "timestamp": slot,
                "hour": slot.hour,
                "price_buy": round(float(row["price_cent_kwh"]), 4),
            }
        )
    prices.sort(key=lambda item: item["timestamp"])
    return prices


def _fetch_awattar_live_fallback(
    planning_end: datetime | None,
) -> list[dict[str, Any]] | None:
    from integrations import awattar_client

    return awattar_client.fetch_awattar_prices(planning_end=planning_end)


def _live_from_cache(
    cached: dict[str, Any],
    *,
    reason: str,
) -> list[dict[str, Any]]:
    live = cached_prices_to_live(cached["prices"], fallback_tz=_planning_tz())
    logger.info(
        "Using cached Energy-Charts %s prices (%s, %s slots, fetched_at=%s)",
        cached["zone"],
        reason,
        len(live),
        cached["fetched_at"].isoformat(),
    )
    return live


def _try_cached_live(
    zone: str,
    window_start: datetime,
    window_end: datetime,
    *,
    now: datetime,
    require_fresh: bool,
) -> list[dict[str, Any]] | None:
    cached = load_live_price_cache(zone, fallback_tz=_planning_tz())
    if cached is None:
        return None
    cover_start = window_start if require_fresh else now
    if not cache_covers_window(
        cached["prices"],
        cover_start,
        window_end,
        fallback_tz=_planning_tz(),
    ):
        return None
    if require_fresh and not cache_is_fresh_for_day_ahead(cached["fetched_at"], now):
        return None
    reason = "covers window, skip fetch" if require_fresh else "Energy-Charts unavailable"
    return _live_from_cache(cached, reason=reason)


def _cached_live_for_zone(zone: str) -> list[dict[str, Any]] | None:
    cached = load_live_price_cache(zone, fallback_tz=_planning_tz())
    if cached is None:
        return None
    live = cached_prices_to_live(cached["prices"], fallback_tz=_planning_tz())
    return live or None


def _fetch_and_cache_energy_charts(
    zone: str,
    window_start: datetime,
    window_end: datetime,
    *,
    fetched_at: datetime,
) -> list[dict[str, Any]]:
    cached_live = _cached_live_for_zone(zone)
    fetch_start = network_fetch_start(
        window_start, window_end, cached_live, fetched_at
    )
    start_ts = pd.Timestamp(fetch_start.replace(tzinfo=None))
    end_ts = pd.Timestamp(window_end.replace(tzinfo=None))
    logger.info(
        "Energy-Charts %s request %s → %s (needed history from %s%s)",
        zone,
        fetch_start.isoformat(),
        window_end.isoformat(),
        window_start.isoformat(),
        "; filled from cache" if fetch_start > window_start else "",
    )
    df = fetch_energy_charts_prices(start_ts, end_ts, bzn=zone)
    fresh = _dataframe_to_live_market_data(df)
    if not fresh:
        raise ValueError("Energy-Charts returned no usable price rows.")
    merged = merge_live_price_series(cached_live or [], fresh)
    live = trim_live_price_series(merged, window_start, window_end)
    if not live:
        raise ValueError("Energy-Charts merge produced no usable price rows.")
    save_live_price_cache(
        zone,
        live,
        fetched_at=fetched_at,
        window_start=window_start,
        window_end=window_end,
    )
    return live


def _awattar_after_cache_miss(
    zone: str,
    planning_end: datetime | None,
) -> list[dict[str, Any]] | None:
    logger.warning(
        "No usable Energy-Charts cache for %s; falling back to aWATTar",
        zone,
    )
    if zone == MARKET_ZONE_CH:
        logger.warning("CH live fallback uses aWATTar AT series (hourly expand).")
    return _fetch_awattar_live_fallback(planning_end)


def fetch_live_day_ahead_prices(
    planning_end: datetime | None = None,
) -> list[dict[str, Any]] | None:
    """
    Live market data for the planning window.

    Prefer Energy-Charts for the house bidding zone. Reuse
    ``runtime/live_energy_charts_<zone>.json`` while it still covers the
    fetch window and is fresh vs. Day-Ahead publish (~12:00). When a refresh
    is needed, request only from today onward if the mirror lookback is
    already cached. On Energy-Charts failure, prefer that QH cache over
    aWATTar (hourly expand) when coverage reaches the planning end.
    """
    zone = _runtime_market_zone()
    start, end = awattar_fetch_window(planning_end)
    now = _now_slot(planning_end)

    cached_hit = _try_cached_live(zone, start, end, now=now, require_fresh=True)
    if cached_hit is not None:
        return cached_hit

    try:
        return _fetch_and_cache_energy_charts(
            zone, start, end, fetched_at=now
        )
    except Exception as exc:
        logger.warning(
            "Energy-Charts %s failed for live prices (%s)",
            zone,
            exc,
        )
        cached_outage = _try_cached_live(
            zone, start, end, now=now, require_fresh=False
        )
        if cached_outage is not None:
            return cached_outage
        return _awattar_after_cache_miss(zone, planning_end)
