"""Live Day-Ahead prices: Energy-Charts first, aWATTar hourly fallback."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import config
from data.data_loader import (
    MARKET_ZONE_AT,
    fetch_energy_charts_prices,
)
from data.market_prices import awattar_fetch_window, normalize_price_slot
from data.tariff_pricing import market_zone_for_land

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


def _dataframe_to_live_market_data(df: pd.DataFrame) -> list[dict[str, Any]]:
    planning_tz = ZoneInfo(config.get_planning_timezone())
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


def fetch_live_day_ahead_prices(
    planning_end: datetime | None = None,
) -> list[dict[str, Any]] | None:
    """
    Live market data for the planning window.

    Prefer Energy-Charts for the house bidding zone; fall back to aWATTar
    (hourly, expanded onto QH slots by resolve_market_slots) on failure.
    """
    zone = _runtime_market_zone()
    start, end = awattar_fetch_window(planning_end)
    start_ts = pd.Timestamp(start.replace(tzinfo=None))
    end_ts = pd.Timestamp(end.replace(tzinfo=None))
    try:
        df = fetch_energy_charts_prices(start_ts, end_ts, bzn=zone)
        live = _dataframe_to_live_market_data(df)
        if live:
            return live
        raise ValueError("Energy-Charts returned no usable price rows.")
    except Exception as exc:
        logger.warning(
            "Energy-Charts %s failed for live prices (%s); falling back to aWATTar",
            zone,
            exc,
        )
        if zone == MARKET_ZONE_CH:
            # CH has no aWATTar; try AT aWATTar only as last resort for connectivity.
            logger.warning("CH live fallback uses aWATTar AT series (hourly expand).")
        return _fetch_awattar_live_fallback(planning_end)
