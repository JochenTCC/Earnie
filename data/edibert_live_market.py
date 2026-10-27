"""Live Day-Ahead prices through Edibert's market chain (Edibert P4a).

Edibert asks its cache, then ENTSO-E (with ``ENTSOE_API_TOKEN``), Energy-Charts and
aWATTar (AT / DE-LU only; CH has no third source). Every HTTP request goes through
:func:`_shadow_get`, so Prod records each answer under its ``ext:prices:*`` feed key
and Shadow replays it. Seven days before today are part of the window: they are the
mirror sources of ``data.market_prices.resolve_market_slots``.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from edibert import api

import config
from data.market_prices import MAX_MIRROR_LOOKBACK_DAYS, normalize_price_slot
from house_config.edibert_tariffs import market_zone
from runtime_store.cycle_duration_stats import (
    EVENT_DAY_AHEAD_FETCH,
    record_event as record_cycle_event,
)
from runtime_store.persist_paths import runtime_path
from runtime_store.planning_clock import planning_now

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 30
CACHE_DIR_NAME = "edibert_market"
_USER_AGENT = "Earnie (energy optimizer; live day-ahead prices)"
_FEED_BY_HOST = {
    "web-api.tp.entsoe.eu": "ext:prices:entsoe",
    "api.energy-charts.info": "ext:prices:energy_charts",
    "api.awattar.at": "ext:prices:awattar",
    "api.awattar.de": "ext:prices:awattar",
}


def _normalize_token(raw: str | None) -> str:
    return str(raw or "").strip().strip('"')


def read_entsoe_api_token() -> str:
    """
    Return ``ENTSOE_API_TOKEN`` from the process env, else from ``config/.env``.

    File fallback covers cases where ``load_dotenv`` did not populate the
    process environment (wrong cwd at import, stale process, etc.).
    """
    from_env = _normalize_token(os.getenv("ENTSOE_API_TOKEN"))
    if from_env:
        return from_env
    try:
        from runtime_store.dotenv_io import _dotenv_values_safe
        from runtime_store.persist_paths import resolve_dotenv_path

        path = resolve_dotenv_path()
        from_file = _normalize_token(
            _dotenv_values_safe(path).get("ENTSOE_API_TOKEN")
        )
    except Exception:  # noqa: BLE001 — never block live prices on path I/O
        return ""
    if from_file:
        os.environ["ENTSOE_API_TOKEN"] = from_file
    return from_file


def feed_key_for_url(url: str) -> str:
    """Shadow feed key of a market-source URL; an unknown host is an error."""
    host = urlparse(url).hostname or ""
    try:
        return _FEED_BY_HOST[host]
    except KeyError:
        raise ValueError(f"No shadow feed key for market source host {host!r}") from None


def _redact(text: str) -> str:
    """Remove the ENTSO-E token from a message that may contain the request URL."""
    return re.sub(r"securityToken=[^&\s'\"]*", "securityToken=REDACTED", text)


def _replay_text(feed_key: str) -> str | None:
    """Recorded payload as text; records before P4a stored Energy-Charts / aWATTar as JSON objects."""
    from runtime_store.shadow.replay import replay_ext_payload

    payload = replay_ext_payload(feed_key)
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload
    return json.dumps(payload)


def _shadow_get(url: str, params: Any, timeout: float) -> str:
    """Edibert ``HttpGet``: shadow-aware request; failures raise ``api.MarketSourceError``."""
    from runtime_store.shadow.mode import is_shadow_mode
    from runtime_store.shadow.transport import ext_get, safe_record

    feed_key = feed_key_for_url(url)

    def _live() -> str:
        # Family B: Shadow fallback must not record; Prod records.
        record = not is_shadow_mode()
        try:
            response = requests.get(
                url,
                params=dict(params),
                headers={"User-Agent": _USER_AGENT},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            reason = _redact(str(exc))
            if record:
                safe_record(feed_key, ok=False, error=reason)
            raise api.MarketSourceError(f"{feed_key}: {reason}") from exc
        if response.status_code >= 400:
            if record:
                safe_record(
                    feed_key,
                    ok=False,
                    status=int(response.status_code),
                    payload=response.text,
                    error=f"HTTP {response.status_code}",
                )
            raise api.MarketSourceError(f"{feed_key}: HTTP {response.status_code}")
        if record:
            safe_record(
                feed_key, ok=True, payload=response.text, status=int(response.status_code)
            )
        return response.text

    return ext_get(
        replay=lambda: _replay_text(feed_key),
        live=_live,
        allow_live_fallback=True,
    )


def _runtime_market_zone() -> str:
    resolved = config.get_resolved_runtime_settings() or {}
    profile = resolved.get("_house_profile") or {}
    land = profile.get("land") or resolved.get("land")
    if not land:
        raise ValueError(
            "Kein Land im Hausprofil — Marktgebiet für Live-Börsenpreise unbekannt."
        )
    return market_zone(str(land))


def _to_live_rows(prices: dict[datetime, float]) -> list[dict[str, Any]]:
    rows = []
    for slot_utc, cent in sorted(prices.items()):
        slot = normalize_price_slot(slot_utc)
        rows.append({"timestamp": slot, "hour": slot.hour, "price_buy": round(float(cent), 4)})
    return rows


def fetch_live_day_ahead_prices(
    planning_end: datetime | None = None,
) -> list[dict[str, Any]] | None:
    """
    Day-Ahead prices for live planning: seven days back up to today, or tomorrow
    from the 12:00 publish on (Edibert ``market_live``).

    ``planning_end`` only sets the time zone of the planning clock; slots beyond the
    last published day are filled by ``resolve_market_slots`` (mirror / forecast).
    Returns ``None`` when no source and no cache has any price.
    """
    tz = (
        planning_end.tzinfo
        if planning_end is not None and planning_end.tzinfo is not None
        else ZoneInfo(config.get_planning_timezone())
    )
    zone = _runtime_market_zone()
    requested: list[str] = []

    def _get(url: str, params: Any, timeout: float) -> str:
        if not requested:
            record_cycle_event(EVENT_DAY_AHEAD_FETCH)
        requested.append(url)
        return _shadow_get(url, params, timeout)

    try:
        data = api.market_live(
            zone,
            Path(runtime_path(CACHE_DIR_NAME)),
            tz,
            entsoe_token=read_entsoe_api_token(),
            get=_get,
            history_days=MAX_MIRROR_LOOKBACK_DAYS,
            timeout=HTTP_TIMEOUT_S,
            now=planning_now(tz),
        )
    except api.EdibertError as exc:
        if exc.code != api.ErrorCode.MARKET_DATA_UNAVAILABLE:
            raise
        logger.error("Keine Day-Ahead-Preise für %s: %s", zone, exc)
        return None
    for note in data.notes:
        logger.warning("Day-Ahead %s: %s (%s)", zone, note.message, note.code)
    logger.info(
        "Day-Ahead %s from %s (%s slots, complete=%s, fetched_at=%s%s)",
        zone,
        data.source,
        len(data.prices),
        data.complete,
        data.fetched_at.isoformat(),
        "" if requested else ", cache",
    )
    return _to_live_rows(data.prices)
