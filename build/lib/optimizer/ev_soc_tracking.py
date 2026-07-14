"""Loxone-Ist-SOC vs. intern berechneter Lade-SOC für E-Auto-Sessions."""
from __future__ import annotations

import logging
from typing import Any

from integrations import loxone_client
from settings.flexible_consumers import charging_efficiency

logger = logging.getLogger(__name__)

SOC_COMPLETE_TOLERANCE_PCT = 0.5
SOC_COMPARE_WARN_DELTA_PCT = 5.0


def _charging_loxone(consumer: dict) -> dict:
    sched = consumer.get("charging_schedule") or {}
    return sched.get("loxone") or {}


def fetch_loxone_actual_soc_percent(consumer: dict) -> float | None:
    """Liest optionalen Loxone-Ist-SOC (z. B. Ernie-SOC-Ist-EAuto), %."""
    io_name = str(_charging_loxone(consumer).get("actual_soc_name", "")).strip()
    if not io_name:
        return None
    raw = loxone_client.fetch_loxone_generic_value(io_name)
    if raw is None:
        return None
    return float(raw)


def target_soc_percent(consumer: dict) -> float:
    sched = consumer.get("charging_schedule") or {}
    return float(sched.get("target_soc_percent", 100.0) or 100.0)


def loxone_reports_charge_complete(consumer: dict) -> bool:
    """True wenn Loxone-Ist-SOC das Ladeziel erreicht hat."""
    actual = fetch_loxone_actual_soc_percent(consumer)
    if actual is None:
        return False
    target = target_soc_percent(consumer)
    return actual >= target - SOC_COMPLETE_TOLERANCE_PCT


def computed_session_soc_percent(
    consumer: dict,
    session: dict[str, Any] | None,
    delivered_kwh: float,
) -> float | None:
    """Interner SOC aus Rest-SOC beim Anschließen plus gebuchter Ladeenergie."""
    if not session:
        return None
    plug_in = session.get("plug_in_rest_soc_percent")
    if plug_in is None:
        return None
    capacity_kwh = loxone_client.resolve_consumer_battery_capacity_kwh(consumer)
    if capacity_kwh is None or float(capacity_kwh) <= 0:
        return None
    sched = consumer.get("charging_schedule") or {}
    eff = charging_efficiency(sched)
    added_pct = (max(0.0, float(delivered_kwh)) * eff / float(capacity_kwh)) * 100.0
    return min(100.0, float(plug_in) + added_pct)


def compare_ev_soc_sources(
    consumer: dict,
    session: dict[str, Any] | None,
    delivered_kwh: float,
    *,
    live_kw: float | None,
) -> dict[str, Any] | None:
    """Vergleicht Loxone-Ist-SOC mit internem SOC, wenn beide verfügbar."""
    loxone_soc = fetch_loxone_actual_soc_percent(consumer)
    computed_soc = computed_session_soc_percent(consumer, session, delivered_kwh)
    if loxone_soc is None or computed_soc is None:
        return None
    if live_kw is None or float(live_kw) <= 0:
        return None
    delta = abs(loxone_soc - computed_soc)
    note: dict[str, Any] = {
        "role": "ev_soc_compare",
        "loxone_soc_percent": round(loxone_soc, 2),
        "computed_soc_percent": round(computed_soc, 2),
        "delta_percent": round(delta, 2),
    }
    if delta >= SOC_COMPARE_WARN_DELTA_PCT:
        logger.warning(
            "%s: Loxone-Ist-SOC %.1f %% weicht von berechnetem SOC %.1f %% ab "
            "(Δ %.1f %%, live=%.2f kW)",
            consumer.get("name", consumer.get("id")),
            loxone_soc,
            computed_soc,
            delta,
            float(live_kw),
        )
        note["warn"] = True
    return note
