"""Lieferbuchung und Soll-Ist-Überwachung für flexible Verbraucher."""
from __future__ import annotations

import logging
from typing import Any

from .charge_immediate import charging_power_threshold_kw, fetch_charge_immediate_switch
from .charging_context import suppresses_live_charging_output
from .charging_session import is_charging_session_context

logger = logging.getLogger(__name__)

DELIVERY_REOPEN_KWH = 0.5


def booking_power_kw(
    consumer: dict,
    ctx: dict | None,
    *,
    planned_kw: float,
    live_kw: float | None,
    book_planned: bool,
) -> float:
    """Leistung für die Energiebuchung in diesem Intervall (kW)."""
    planned = max(0.0, float(planned_kw or 0.0))
    live = None if live_kw is None else max(0.0, float(live_kw))
    if suppresses_live_charging_output(ctx):
        return 0.0
    if is_charging_session_context(consumer, ctx):
        if live is not None and live > 0:
            return live
        if book_planned and planned > 0:
            return planned
        return 0.0
    if book_planned and planned > 0:
        return planned
    return 0.0


def _charge_immediate_from_snapshot(
    consumer_id: str,
    trigger_snapshot: dict[str, Any] | None,
) -> bool | None:
    if not trigger_snapshot:
        return None
    if f"{consumer_id}_charge_immediate" not in trigger_snapshot:
        return None
    return bool(trigger_snapshot[f"{consumer_id}_charge_immediate"])


def session_still_needs_charge(
    consumer: dict,
    ctx: dict | None,
    *,
    live_kw: float | None,
    charge_immediate_on: bool | None,
) -> bool:
    """True wenn trotz voller Buchung weiter geladen werden muss."""
    if ctx is None or not is_charging_session_context(consumer, ctx):
        return False
    if not ctx.get("plugged_in"):
        return False
    if ctx.get("immediate_charge"):
        return charge_immediate_on is True
    if charge_immediate_on is True:
        return True
    threshold = charging_power_threshold_kw()
    return live_kw is not None and live_kw >= threshold


def effective_session_delivered_kwh(
    delivered_kwh: float,
    target_kwh: float,
    *,
    still_needs: bool,
) -> float:
    if not still_needs or target_kwh <= 0:
        return float(delivered_kwh)
    cap = max(0.0, float(target_kwh) - DELIVERY_REOPEN_KWH)
    return min(float(delivered_kwh), cap)


def assess_session_delivery(
    consumer: dict,
    ctx: dict | None,
    delivered_kwh: float,
    *,
    live_kw: float | None,
    trigger_snapshot: dict[str, Any] | None,
) -> tuple[float, dict[str, Any] | None]:
    """Liefert wirksam gebuchte kWh und optional einen Plausibilitäts-Hinweis."""
    if ctx is None or not is_charging_session_context(consumer, ctx):
        return float(delivered_kwh), None

    target_kwh = float(ctx.get("target_kwh") or 0.0)
    remaining_before = max(0.0, target_kwh - float(delivered_kwh))
    if remaining_before > DELIVERY_REOPEN_KWH:
        return float(delivered_kwh), None

    immediate = _charge_immediate_from_snapshot(consumer["id"], trigger_snapshot)
    if immediate is None:
        immediate = fetch_charge_immediate_switch(consumer)

    still_needs = session_still_needs_charge(
        consumer,
        ctx,
        live_kw=live_kw,
        charge_immediate_on=immediate,
    )
    if not still_needs:
        return float(delivered_kwh), None

    effective = effective_session_delivered_kwh(
        delivered_kwh,
        target_kwh,
        still_needs=True,
    )
    note = {
        "role": "session_reopened",
        "target_kwh": round(target_kwh, 3),
        "booked_delivered_kwh": round(float(delivered_kwh), 3),
        "effective_delivered_kwh": round(effective, 3),
        "live_kw": round(float(live_kw), 3) if live_kw is not None else None,
        "charge_immediate": immediate,
    }
    logger.warning(
        "%s: Ladesession trotz voller Buchung noch aktiv "
        "(gebucht %.3f kWh, wirksam %.3f kWh, live=%.2f kW, Sofortladen=%s)",
        consumer["name"],
        delivered_kwh,
        effective,
        live_kw if live_kw is not None else 0.0,
        immediate,
    )
    return effective, note


def build_delivery_compliance_row(
    consumer: dict,
    ctx: dict | None,
    *,
    planned_kw: float,
    live_kw: float | None,
    sent_kw: float | None,
    booked_kw: float,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "planned_kw": round(float(planned_kw or 0.0), 3),
        "booked_kw": round(float(booked_kw), 3),
    }
    if live_kw is not None:
        row["live_kw"] = round(float(live_kw), 3)
    if sent_kw is not None:
        row["sent_kw"] = round(float(sent_kw), 3)
    if is_charging_session_context(consumer, ctx):
        row["source"] = "live" if live_kw and live_kw > 0 else "planned"
    else:
        row["source"] = "planned"
    return row
