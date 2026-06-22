"""
consumer_targets.py – Tagesziele (kWh) je flexiblem Verbraucher.

Kann Live-Loxone-IO lesen (daily_target_source=loxone); profile_manager bleibt datenneutral.
"""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

import config
import loxone_client
from . import profile_manager


def _historical_totals_for_date(target_date: date, cache: dict) -> dict[str, float]:
    if target_date not in cache:
        _, totals, _ = profile_manager.get_historical_day_data(target_date)
        cache[target_date] = totals
    return cache[target_date]


def _resolve_single_consumer_daily_target_kwh(
    consumer: dict,
    target_date: date,
    matrix: list | None = None,
    historical_cache: dict | None = None,
) -> float:
    """
    Tagesziel (kWh) gemäß daily_target_source: config | historical | loxone.
    """
    source = consumer.get("daily_target_source", "config")
    cid = consumer["id"]
    fallback = float(consumer.get("daily_target_kwh", 0.0) or 0.0)
    cache = historical_cache if historical_cache is not None else {}

    if source == "config":
        if consumer.get("charging_schedule", {}).get("enabled"):
            computed = config.Config.target_kwh_from_day_schedule(
                consumer, datetime.combine(target_date, time(12, 0))
            )
            if computed is not None:
                return computed
        return fallback

    if source == "historical":
        if matrix:
            day_rows = [row for row in matrix if row.get("date") == target_date]
            if day_rows and any(row.get("expected_flex_kw") for row in day_rows):
                return sum(
                    float((row.get("expected_flex_kw") or {}).get(cid, 0.0))
                    for row in day_rows
                )
        totals = _historical_totals_for_date(target_date, cache)
        if cid in totals:
            return float(totals[cid])
        return fallback

    if source == "loxone":
        loxone_name = consumer.get("loxone_target_kwh_name", "")
        today = datetime.now().date()
        if loxone_name and target_date == today:
            value = loxone_client.fetch_loxone_generic_value(loxone_name)
            if value is not None and value >= 0:
                return float(value)
        totals = _historical_totals_for_date(target_date, cache)
        if cid in totals:
            return float(totals[cid])
        return fallback

    return fallback


def resolve_historical_consumer_daily_targets(target_date: date) -> dict[str, float]:
    """Geloggte Tagesenergie je Verbraucher aus cons_data_hourly."""
    if isinstance(target_date, str):
        target_date = pd.to_datetime(target_date).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    _, totals, _ = profile_manager.get_historical_day_data(target_date)
    consumers = config.get_flexible_consumers(optimizer_only=True)
    return {c["id"]: float(totals.get(c["id"], 0.0)) for c in consumers}


def resolve_horizon_flex_targets_kwh(matrix: list) -> dict[str, float]:
    """Summiert expected_flex_kw über den 24h-Horizont."""
    consumers = config.get_flexible_consumers(optimizer_only=True)
    totals = {c["id"]: 0.0 for c in consumers}
    for row in matrix[:24]:
        flex = row.get("expected_flex_kw") or {}
        for consumer in consumers:
            cid = consumer["id"]
            totals[cid] += float(flex.get(cid, 0.0) or 0.0)
    return {cid: round(kwh, 3) for cid, kwh in totals.items()}


def resolve_consumer_daily_targets(
    matrix: list | None = None,
    target_date: date | None = None,
    prefer_logged_totals: bool = False,
) -> dict:
    """
    Tagesziele pro Verbraucher gemäß config.json.
    prefer_logged_totals=True: nur geloggte Tages-Summen (historischer Tag).
    """
    if prefer_logged_totals:
        day = target_date
        if matrix and not day:
            dates = {row["date"] for row in matrix if row.get("date") is not None}
            if len(dates) == 1:
                day = next(iter(dates))
        if day is None:
            raise ValueError("Historische Tagesziele benötigen ein gültiges Datum.")
        return resolve_historical_consumer_daily_targets(day)

    consumers = config.get_flexible_consumers(optimizer_only=True)
    historical_cache: dict = {}

    if matrix:
        dates = sorted({row["date"] for row in matrix if row.get("date") is not None})
        if len(dates) > 1:
            return {
                day: {
                    c["id"]: _resolve_single_consumer_daily_target_kwh(
                        c, day, matrix, historical_cache
                    )
                    for c in consumers
                }
                for day in dates
            }
        day = dates[0] if dates else (target_date or datetime.now().date())
        return {
            c["id"]: _resolve_single_consumer_daily_target_kwh(c, day, matrix, historical_cache)
            for c in consumers
        }

    day = target_date or datetime.now().date()
    return {
        c["id"]: _resolve_single_consumer_daily_target_kwh(c, day, None, historical_cache)
        for c in consumers
    }


def get_forecast_consumer_daily_targets(matrix: list) -> dict:
    """Legacy-Alias für resolve_consumer_daily_targets."""
    return resolve_consumer_daily_targets(matrix=matrix)
