"""
consumer_targets.py – Tagesziele (kWh) je flexiblem Verbraucher.

Kann Live-Loxone-IO lesen (daily_target_source=loxone); profile_manager bleibt datenneutral.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time

import pandas as pd

import config
from integrations import loxone_client
from . import profile_manager

logger = logging.getLogger(__name__)

LOXONE_DEBT_HOURS_EPS = 1e-6


def uses_loxone_debt_counter(consumer: dict) -> bool:
    """True wenn der Loxone-Schuldenzähler die alleinige Restquelle ist (ohne delivered-Abzug)."""
    return consumer.get("daily_target_source") == "loxone_remaining_hours"


def _loxone_remaining_hours_target_kwh(consumer: dict, hours: float | None) -> float:
    cid = consumer["id"]
    loxone_name = consumer.get("loxone_target_hours_name", "")
    if hours is None:
        logger.warning(
            "Verbraucher '%s': Merker '%s' nicht lesbar — Verbraucher inaktiv.",
            cid,
            loxone_name,
        )
        return 0.0
    if hours <= LOXONE_DEBT_HOURS_EPS:
        logger.warning(
            "Verbraucher '%s': Sollstunden=%.4f — Verbraucher inaktiv.",
            cid,
            hours,
        )
        return 0.0
    power = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    return float(hours) * power


def _historical_totals_for_date(target_date: date, cache: dict) -> dict[str, float]:
    if target_date not in cache:
        _, totals, _ = profile_manager.get_historical_day_data(target_date)
        cache[target_date] = totals
    return cache[target_date]


def _historical_target_kwh(
    consumer: dict,
    target_date: date,
    matrix: list | None,
    historical_cache: dict,
) -> float:
    """Historisches Tagesziel unabhängig von daily_target_source."""
    probe = dict(consumer)
    probe["daily_target_source"] = "historical"
    return _resolve_single_consumer_daily_target_kwh(
        probe, target_date, matrix, historical_cache
    )


def _resolve_single_consumer_daily_target_kwh(
    consumer: dict,
    target_date: date,
    matrix: list | None = None,
    historical_cache: dict | None = None,
) -> float:
    """
    Tagesziel (kWh) gemäß daily_target_source:
    config | historical | loxone | loxone_remaining_hours | thermal.
    """
    source = consumer.get("daily_target_source", "config")
    cid = consumer["id"]
    fallback = float(consumer.get("daily_target_kwh", 0.0) or 0.0)
    cache = historical_cache if historical_cache is not None else {}

    if source == "thermal":
        today = datetime.now().date()
        if target_date != today:
            return _historical_target_kwh(consumer, target_date, matrix, cache)
        from optimizer.thermal_targets import resolve_thermal_daily_target_kwh

        if matrix:
            horizon = max(1, len(matrix))
        else:
            horizon = 24
        return resolve_thermal_daily_target_kwh(consumer, horizon=horizon)

    if source == "config":
        if consumer.get("charging_schedule", {}).get("enabled"):
            capacity_kwh = loxone_client.resolve_consumer_battery_capacity_kwh(consumer)
            computed = config.Config.target_kwh_from_day_schedule(
                consumer,
                datetime.combine(target_date, time(12, 0)),
                capacity_kwh=capacity_kwh,
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

    if source == "loxone_remaining_hours":
        loxone_name = consumer.get("loxone_target_hours_name", "")
        today = datetime.now().date()
        if loxone_name and target_date == today:
            hours = loxone_client.fetch_loxone_generic_value(loxone_name)
            return _loxone_remaining_hours_target_kwh(consumer, hours)
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
    """Summiert expected_flex_kw über den gesamten Planungshorizont."""
    consumers = config.get_flexible_consumers(optimizer_only=True)
    totals = {c["id"]: 0.0 for c in consumers}
    for row in matrix:
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


def resolve_historical_baseline_targets_kwh(
    matrix: list | None = None,
    target_date: date | None = None,
) -> dict[str, float]:
    """Historische Tagesziele je Verbraucher (Vergleichsbasis für thermal active)."""
    consumers = config.get_flexible_consumers(optimizer_only=True)
    cache: dict = {}
    if matrix:
        dates = sorted({row["date"] for row in matrix if row.get("date") is not None})
        day = dates[0] if dates else (target_date or datetime.now().date())
    else:
        day = target_date or datetime.now().date()
    return {
        c["id"]: _historical_target_kwh(c, day, matrix, cache)
        for c in consumers
    }


def get_forecast_consumer_daily_targets(matrix: list) -> dict:
    """Legacy-Alias für resolve_consumer_daily_targets."""
    return resolve_consumer_daily_targets(matrix=matrix)
