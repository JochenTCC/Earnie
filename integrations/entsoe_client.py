"""ENTSO-E Transparency Platform day-ahead prices (A44)."""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd
import requests

from data.data_loader import (
    MARKET_ZONE_AT,
    MARKET_ZONE_CH,
    MARKET_ZONE_DE,
    _prices_to_dataframe,
)

logger = logging.getLogger(__name__)

ENTSOE_API_URL = "https://web-api.tp.entsoe.eu/api"
_NS_URI = "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"
_NS = {"p": _NS_URI}

ZONE_TO_EIC: dict[str, str] = {
    MARKET_ZONE_AT: "10YAT-APG------L",
    MARKET_ZONE_DE: "10Y1001A1001A82H",
    MARKET_ZONE_CH: "10YCH-SWISSGRIDZ",
}

_RESOLUTION_MINUTES = {
    "PT15M": 15,
    "PT60M": 60,
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


def entsoe_dotenv_path_for_log() -> str:
    """Absolute ``.env`` path for skip/diagnostic log lines."""
    try:
        from runtime_store.persist_paths import resolve_dotenv_path

        return os.path.abspath(resolve_dotenv_path())
    except Exception:  # noqa: BLE001
        return "config/.env"


def redact_entsoe_url(url: str) -> str:
    """Strip ``securityToken`` from a request URL for safe logging."""
    parts = urlparse(url)
    query = [
        (key, "REDACTED" if key == "securityToken" else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunparse(parts._replace(query=urlencode(query)))


def _period_utc_stamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("ENTSO-E period bounds require timezone-aware datetimes.")
    return moment.astimezone(timezone.utc).strftime("%Y%m%d%H%M")


def _resolution_step_minutes(resolution: str) -> int:
    step = _RESOLUTION_MINUTES.get(str(resolution or "").strip().upper())
    if step is None:
        raise ValueError(f"Unsupported ENTSO-E resolution: {resolution!r}")
    return step


def _child_text(parent: ET.Element, path: str) -> str:
    node = parent.find(path, _NS)
    if node is None or node.text is None:
        return ""
    return str(node.text).strip()


def parse_entsoe_a44_xml(xml_text: str) -> pd.DataFrame:
    """
    Parse A44 Publication_MarketDocument XML into Earnie price DataFrame.

    EUR/MWh → cent/kWh; PT60M expanded to four QH slots; index is naive
    Europe/Vienna (same as ``_prices_to_dataframe``).
    """
    root = ET.fromstring(xml_text)
    if "Acknowledgement" in root.tag:
        reason = _child_text(root, ".//{*}text") or root.tag
        raise ValueError(f"ENTSO-E acknowledgement: {reason}")

    timestamps: list[pd.Timestamp] = []
    prices_eur_mwh: list[float] = []

    for series in root.findall("p:TimeSeries", _NS):
        for period in series.findall("p:Period", _NS):
            start_raw = _child_text(period, "p:timeInterval/p:start")
            resolution = _child_text(period, "p:resolution")
            if not start_raw or not resolution:
                continue
            step_min = _resolution_step_minutes(resolution)
            period_start = pd.Timestamp(start_raw)
            if period_start.tzinfo is None:
                period_start = period_start.tz_localize("UTC")
            for point in period.findall("p:Point", _NS):
                pos_raw = _child_text(point, "p:position")
                price_raw = _child_text(point, "p:price.amount")
                if not pos_raw or not price_raw:
                    continue
                position = int(pos_raw)
                price = float(price_raw)
                slot_start = period_start + pd.Timedelta(
                    minutes=step_min * (position - 1)
                )
                if step_min == 15:
                    timestamps.append(slot_start)
                    prices_eur_mwh.append(price)
                    continue
                for offset in range(0, step_min, 15):
                    timestamps.append(slot_start + pd.Timedelta(minutes=offset))
                    prices_eur_mwh.append(price)

    if not timestamps:
        raise ValueError("ENTSO-E A44 XML contained no usable price points.")
    return _prices_to_dataframe(pd.Series(timestamps), pd.Series(prices_eur_mwh))


def fetch_entsoe_day_ahead_prices(
    start: datetime,
    end: datetime,
    zone: str,
    token: str | None = None,
    *,
    timeout: int = 30,
) -> pd.DataFrame | None:
    """
    Fetch day-ahead prices for ``zone`` from ENTSO-E Transparency.

    Returns ``None`` when no token is configured (logged once at INFO). Raises
    on HTTP/parse failures so the live orchestrator can fall through.
    """
    security_token = (
        _normalize_token(token) if token is not None else read_entsoe_api_token()
    )
    if not security_token:
        logger.info(
            "ENTSO-E skipped (no ENTSOE_API_TOKEN); checked %s — "
            "falling through to Energy-Charts",
            entsoe_dotenv_path_for_log(),
        )
        return None
    eic = ZONE_TO_EIC.get(str(zone).strip())
    if not eic:
        raise ValueError(f"No ENTSO-E EIC mapping for market zone {zone!r}")

    params = {
        "documentType": "A44",
        "contract_MarketAgreement.type": "A01",
        "in_Domain": eic,
        "out_Domain": eic,
        "periodStart": _period_utc_stamp(start),
        "periodEnd": _period_utc_stamp(end),
        "securityToken": security_token,
    }
    logger.info(
        "ENTSO-E %s request %s → %s (eic=%s)",
        zone,
        params["periodStart"],
        params["periodEnd"],
        eic,
    )

    response = requests.get(ENTSOE_API_URL, params=params, timeout=timeout)
    if response.status_code >= 400:
        logger.warning(
            "ENTSO-E %s HTTP %s (%s)",
            zone,
            response.status_code,
            redact_entsoe_url(response.url),
        )
        response.raise_for_status()
    return parse_entsoe_a44_xml(response.text)
