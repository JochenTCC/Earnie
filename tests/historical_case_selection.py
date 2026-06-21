# tests/historical_case_selection.py
"""Auswahl historischer Testtage: pro Monat je ein PV-reicher und ein PV-armer Tag."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from simulation_engine import (
    HistoricalDataCache,
    window_anchor_for_date,
    window_slot_datetimes,
)


@dataclass(frozen=True)
class HistoricalConsistencyCase:
    """Ein 24h-Fenster mit ready_by_hour am Ende."""

    anchor_date: date
    anchor: datetime
    label: str
    pv_kwh: float
    load_kwh: float

    @property
    def case_id(self) -> str:
        return f"{self.anchor_date.isoformat()}_{self.label}"


def _data_bounds(cache: HistoricalDataCache) -> tuple[date, date]:
    cache.load()
    idx = cache._consumption_df.index
    return idx.min().date(), idx.max().date()


def select_monthly_pv_extreme_cases(
    cache: HistoricalDataCache | None = None,
    months_back: int = 12,
) -> list[HistoricalConsistencyCase]:
    """
    Wählt pro Kalendermonat zwei Tage mit gültigem 24h-Fenster:
    höchste und niedrigste PV-Energie im Fenster [ready_by_hour - 24h, ready_by_hour).
    """
    cache = cache or HistoricalDataCache()
    cache.load()
    data_start, data_end = _data_bounds(cache)
    range_end = data_end
    range_start = max(data_start, range_end - timedelta(days=months_back * 31))

    by_month: dict[tuple[int, int], list[tuple[date, datetime, float, float]]] = {}
    for day in pd.date_range(range_start, range_end, freq="D"):
        anchor = window_anchor_for_date(day.date())
        slots = window_slot_datetimes(anchor)
        if slots[0].date() < data_start or slots[-1].date() > data_end:
            continue
        _, _, total_load = cache.get_window_consumption(slots)
        load_kwh = float(sum(total_load))
        if load_kwh <= 0:
            continue
        pv_kwh = float(sum(cache.get_pv_for_slots(slots)))
        month_key = (day.year, day.month)
        by_month.setdefault(month_key, []).append((day.date(), anchor, pv_kwh, load_kwh))

    cases: list[HistoricalConsistencyCase] = []
    month_keys = sorted(by_month.keys())[-months_back:]
    for month_key in month_keys:
        days = by_month[month_key]
        if len(days) < 1:
            continue
        high = max(days, key=lambda item: item[2])
        low = min(days, key=lambda item: item[2])
        cases.append(
            HistoricalConsistencyCase(
                anchor_date=high[0],
                anchor=high[1],
                label="high_pv",
                pv_kwh=round(high[2], 3),
                load_kwh=round(high[3], 3),
            )
        )
        if low[0] != high[0]:
            cases.append(
                HistoricalConsistencyCase(
                    anchor_date=low[0],
                    anchor=low[1],
                    label="low_pv",
                    pv_kwh=round(low[2], 3),
                    load_kwh=round(low[3], 3),
                )
            )
        else:
            cases.append(
                HistoricalConsistencyCase(
                    anchor_date=low[0],
                    anchor=low[1],
                    label="single_day",
                    pv_kwh=round(low[2], 3),
                    load_kwh=round(low[3], 3),
                )
            )
    return cases
