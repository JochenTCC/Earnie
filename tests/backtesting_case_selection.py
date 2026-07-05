"""Auswahl kompakter Backtesting-Fenster für schnelle Integrationstests."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from simulation.engine import (
    HistoricalDataCache,
    list_simulation_anchors,
    window_slot_datetimes,
)

# Fenster mit geloggtem E-Auto-Ladeziel > Schwelle lösen CBC sehr lange / hängen
# (use_time_window=True + variable E-Auto-Leistung). Für Smoke-Tests ohne E-Auto wählen.
DEFAULT_MAX_EAUTO_KWH = 0.05


def select_backtesting_smoke_anchor(
    cache: HistoricalDataCache | None = None,
    *,
    prefer_date: date | None = None,
    max_eauto_kwh: float = DEFAULT_MAX_EAUTO_KWH,
) -> datetime:
    """
    Liefert einen 24h-Anker mit gültigen Log-Daten und minimalem E-Auto-Verbrauch.

    Ziel: run_simulation in wenigen Sekunden statt Minuten (kein schweres E-Auto-MILP).
    """
    cache = cache or HistoricalDataCache()
    cache.load()
    idx = cache._consumption_df.index
    data_start = pd.Timestamp(idx.min()).normalize()
    data_end = pd.Timestamp(idx.max()).normalize()

    if prefer_date is not None:
        preferred = pd.Timestamp(prefer_date)
        if data_start <= preferred <= data_end:
            anchors = list_simulation_anchors(preferred, preferred, cache)
            if anchors:
                anchor = anchors[0]
                totals = _flex_totals_for_anchor(cache, anchor)
                if totals.get("eauto", 0.0) <= max_eauto_kwh:
                    return anchor

    best_anchor: datetime | None = None
    best_eauto = float("inf")
    search_start = max(data_start, data_end - pd.Timedelta(days=90))
    for day in pd.date_range(search_start, data_end, freq="D"):
        anchors = list_simulation_anchors(day, day, cache)
        if not anchors:
            continue
        anchor = anchors[0]
        totals = _flex_totals_for_anchor(cache, anchor)
        eauto_kwh = float(totals.get("eauto", 0.0))
        if eauto_kwh > max_eauto_kwh:
            continue
        if eauto_kwh < best_eauto:
            best_eauto = eauto_kwh
            best_anchor = anchor

    if best_anchor is None:
        raise ValueError(
            "Kein Backtesting-Smoke-Anker gefunden "
            f"(E-Auto-Verbrauch <= {max_eauto_kwh} kWh pro 24h-Fenster)."
        )
    return best_anchor


def _flex_totals_for_anchor(cache: HistoricalDataCache, anchor: datetime) -> dict[str, float]:
    slots = window_slot_datetimes(anchor)
    _, totals, _, _ = cache.get_window_consumption(slots)
    return totals
