"""Energy-Charts API of Fraunhofer ISE (https://energy-charts.info/, data CC BY 4.0).

Requests whose last day is settled are served from the session's disk cache.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from opendata.http import Session

BASE_URL = "https://api.energy-charts.info"
HOST = "api.energy-charts.info"
# Answers often take longer than a short default timeout, especially for whole months.
TIMEOUT_FLOOR_S = 30.0
# Energy-Charts revises load and generation of the most recent days.
SETTLE_DAYS = 2


def _timeout(session: Session) -> float:
    return max(session.timeout_s, TIMEOUT_FLOOR_S)


def public_power(session: Session, *, country: str, start: date, end: date) -> dict[str, Any]:
    """``public_power`` payload for the local days ``start`` … ``end`` (both inclusive)."""
    payload = session.get_json_cached(
        f"{BASE_URL}/public_power",
        {"country": country, "start": start.isoformat(), "end": end.isoformat()},
        last_day=end,
        settle_days=SETTLE_DAYS,
        timeout_s=_timeout(session),
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Unerwartete API-Antwort von {BASE_URL}/public_power")
    return payload


def price(session: Session, *, bzn: str, start: date, end: date) -> dict[str, Any]:
    """Day-Ahead ``price`` payload (EUR/MWh) of bidding zone ``bzn`` for ``start`` … ``end`` (inclusive)."""
    payload = session.get_json_cached(
        f"{BASE_URL}/price",
        {"bzn": bzn, "start": start.isoformat(), "end": end.isoformat()},
        last_day=end,
        settle_days=SETTLE_DAYS,
        timeout_s=_timeout(session),
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Unerwartete API-Antwort von {BASE_URL}/price")
    return payload
