"""Day-Ahead-Preise für das rollierende 24h-Fenster inkl. Spiegel-Extrapolation."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

import config

PRICE_SOURCE_DAY_AHEAD = "day_ahead"
PRICE_SOURCE_MIRRORED = "mirrored"


def normalize_price_slot(dt: datetime) -> datetime:
    """Stunden-Slot (lokale Zeit, ohne Minuten/Sekunden)."""
    return dt.replace(minute=0, second=0, microsecond=0)


def epex_to_brutto_cent(epex_price_cent: float) -> float:
    """EPEX Cent/kWh → Endkunden-Bruttopreis laut config."""
    fix_aufschlag = config.get("FIX_AUFSCHLAG_CENT", cast=float)
    netzverlust = config.get("NETZVERLUST_FAKTOR", cast=float)
    mwst_faktor = config.get("MWST_AUSTRIA_FAKTOR", cast=float)
    brutto = (float(epex_price_cent) * netzverlust + fix_aufschlag) * mwst_faktor
    return round(brutto, 4)


def index_market_data_by_slot(market_data: list[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    """Indiziert Roh-Marktdaten nach Stunden-Slot (Mittelwert bei Duplikaten)."""
    buckets: dict[datetime, list[float]] = {}
    for item in market_data:
        ts = item.get("timestamp")
        if ts is None:
            continue
        slot = normalize_price_slot(ts)
        try:
            price = float(item["price_buy"])
        except (KeyError, TypeError, ValueError):
            continue
        buckets.setdefault(slot, []).append(price)

    indexed: dict[datetime, dict[str, Any]] = {}
    for slot, prices in buckets.items():
        epex = sum(prices) / len(prices)
        indexed[slot] = {
            "timestamp": slot,
            "hour": slot.hour,
            "price_buy": round(epex, 4),
        }
    return indexed


def resolve_24h_market_slots(
    market_data: list[dict[str, Any]],
    target_hours: list[datetime],
) -> list[dict[str, Any]]:
    """
    Liefert genau 24 Preis-Slots für target_hours.

    Fehlende Day-Ahead-Stunden werden per Spiegelung befüllt:
    gleiche Uhrzeit am Vortag (typisch: morgen früh ← heute früh).
    """
    if len(target_hours) != 24:
        raise ValueError(
            f"resolve_24h_market_slots erwartet 24 Zielstunden, erhielt {len(target_hours)}."
        )

    by_slot = index_market_data_by_slot(market_data)
    resolved: list[dict[str, Any]] = []

    for target_dt in target_hours:
        slot = normalize_price_slot(target_dt)
        if slot in by_slot:
            epex = float(by_slot[slot]["price_buy"])
            resolved.append(
                {
                    "slot_datetime": slot,
                    "hour": slot.hour,
                    "price_buy": epex,
                    "price_source": PRICE_SOURCE_DAY_AHEAD,
                    "k_act": epex_to_brutto_cent(epex),
                }
            )
            continue

        mirror_slot = slot - timedelta(days=1)
        if mirror_slot not in by_slot:
            raise ValueError(
                f"Kein Day-Ahead-Preis für {slot:%Y-%m-%d %H:%M} und keine Spiegelquelle "
                f"für {mirror_slot:%Y-%m-%d %H:%M} verfügbar. "
                "aWATTar-Zeitraum erweitern oder später erneut versuchen."
            )

        epex = float(by_slot[mirror_slot]["price_buy"])
        resolved.append(
            {
                "slot_datetime": slot,
                "hour": slot.hour,
                "price_buy": epex,
                "price_source": PRICE_SOURCE_MIRRORED,
                "mirrored_from": mirror_slot,
                "k_act": epex_to_brutto_cent(epex),
            }
        )

    return resolved


def awattar_fetch_window() -> tuple[datetime, datetime]:
    """Start (Mitternacht heute) und Ende (jetzt + 24h) für den aWATTar-Abruf."""
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now + timedelta(hours=24)
    return start, end


def epex_prices_for_slots(
    prices_df: pd.DataFrame,
    slot_datetimes: list[datetime],
) -> list[float]:
    """EPEX Cent/kWh je Stunden-Slot aus einem Preis-DataFrame."""
    hourly = prices_df["price_cent_kwh"].resample("h").mean()
    idx = pd.DatetimeIndex(slot_datetimes)
    series = hourly.reindex(idx).ffill().bfill().fillna(0.0)
    return [float(p) for p in series.tolist()]
