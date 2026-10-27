"""Market prices for the SE and backtesting through Edibert's archive (Edibert P4b).

``price_source: api`` asks :class:`edibert.api.MarketArchive` (Energy-Charts, one cache file per
UTC month under ``runtime/edibert_market/market_archive/<zone>/``, HTTP 429 waited out). There is no
aWATTar fallback: without an answer and without a cache the run fails. ``price_source: csv`` reads an
Energy-Charts CSV download (offline source, test fixtures).

Both return the frame the SE works with: naive Vienna time index ``ts_price``, column
``price_cent_kwh``; the two quarter-hours of the repeated autumn hour are averaged as before.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
from edibert import api

from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

PRICE_INDEX_TZ = "Europe/Vienna"
CACHE_DIR_NAME = "edibert_market"


def energy_charts_price_column(zone: str) -> str:
    """Spaltenname der Energy-Charts-CSV für eine Marktzone (z. B. ``Day Ahead Auktion (AT)``)."""
    return f"Day Ahead Auktion ({zone})"


def _local_frame(stamps: pd.Series, cents: pd.Series) -> pd.DataFrame:
    """UTC stamps + cent/kWh → naive Vienna index, duplicates (autumn hour) averaged."""
    frame = pd.DataFrame(
        {
            "ts_price": pd.to_datetime(stamps, utc=True)
            .dt.tz_convert(PRICE_INDEX_TZ)
            .dt.tz_localize(None)
            .to_numpy(),
            "price_cent_kwh": pd.to_numeric(cents, errors="coerce").to_numpy(),
        }
    ).dropna()
    return frame.groupby("ts_price")["price_cent_kwh"].mean().dropna().to_frame()


def _archive_prices(
    zone: str, start: pd.Timestamp, end: pd.Timestamp, timeout: float
) -> pd.DataFrame:
    first = start.normalize().tz_localize(PRICE_INDEX_TZ).to_pydatetime()
    last = (end.normalize() + pd.Timedelta(days=1)).tz_localize(PRICE_INDEX_TZ).to_pydatetime()
    archive = api.MarketArchive(zone, Path(runtime_path(CACHE_DIR_NAME)), timeout=timeout)
    data = archive.prices(first, last)
    for note in data.notes:
        logger.warning("Marktpreise %s: %s (%s)", zone, note.message, note.code)
    slots = sorted(data.prices)
    return _local_frame(pd.Series(slots), pd.Series([data.prices[slot] for slot in slots]))


def _csv_prices(price_csv_path: str, zone: str) -> pd.DataFrame:
    """Preise der Marktzone ``zone`` aus einer Energy-Charts-CSV-Datei."""
    if not os.path.isfile(price_csv_path):
        raise FileNotFoundError(f"Preis-CSV fehlt: {price_csv_path}")
    raw = pd.read_csv(price_csv_path, sep=",", skiprows=[1])
    price_col = energy_charts_price_column(zone)
    if price_col not in raw.columns:
        raise ValueError(
            f"{price_csv_path}: Spalte '{price_col}' für Marktzone {zone} fehlt "
            f"(vorhanden: {', '.join(map(str, raw.columns))})."
        )
    return _local_frame(raw["Datum (MEZ)"], pd.to_numeric(raw[price_col], errors="coerce") * 0.1)


def load_market_prices(
    start: pd.Timestamp,
    end: pd.Timestamp,
    sim_cfg: dict,
    timeout: float = 30,
    *,
    market_zone: str | None = None,
) -> pd.DataFrame:
    """Day-Ahead-Preise (Cent/kWh) für die Tage ``start`` bis ``end`` (inklusive).

    Marktzone: ``market_zone``, sonst ``energy_charts_bzn`` der SE-Konfiguration; ohne beide ein Fehler.
    """
    zone = market_zone or sim_cfg.get("energy_charts_bzn")
    if not zone:
        raise ValueError("Keine Marktzone für die Börsenpreise der Simulation angegeben.")
    if sim_cfg.get("price_source", "csv") == "api":
        df_prices = _archive_prices(str(zone), start, end, timeout)
    else:
        path_price = sim_cfg.get("path_price")
        if not path_price:
            raise ValueError("price_source='csv' erfordert 'path_price' in der Konfiguration.")
        df_prices = _csv_prices(path_price, str(zone))

    mask = (df_prices.index >= start) & (df_prices.index < end + pd.Timedelta(days=1))
    df_prices = df_prices.loc[mask]
    if df_prices.empty:
        raise ValueError(f"Keine Preisdaten für {start.date()} bis {end.date()} gefunden.")
    return df_prices
