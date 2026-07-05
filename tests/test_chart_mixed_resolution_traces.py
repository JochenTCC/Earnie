"""Tests für Preis/Balken auf gemischter 15-min/1-h-Chart-Achse."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ui.charts import (
    ChartSlotAxis,
    _bar_widths_ms,
    _hour_prices_from_df,
    _hourly_price_hv_xy,
)

_TZ = ZoneInfo("Europe/Vienna")


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 5, hour, minute, tzinfo=_TZ)


def _mixed_slots() -> list[datetime]:
    quarters = [_dt(6, 0), _dt(6, 15), _dt(6, 30), _dt(6, 45)]
    hours = [_dt(h, 0) for h in range(7, 10)]
    return quarters + hours


def test_hour_prices_from_df_one_price_per_hour():
    slots = _mixed_slots()
    rows = []
    for index, slot in enumerate(slots):
        hour = slot.replace(minute=0, second=0, microsecond=0)
        price = 10.0 + hour.hour
        if slot.minute == 15:
            price += 0.5
        rows.append({
            "slot_datetime": slot,
            "Strompreis (Cent/kWh)": price,
        })
    df = pd.DataFrame(rows)
    hour_prices = _hour_prices_from_df(df)
    assert len(hour_prices) == 4
    assert hour_prices[0] == (_dt(6, 0), 16.0)
    assert hour_prices[1] == (_dt(7, 0), 17.0)


def test_hourly_price_hv_steps_only_at_hour_boundaries():
    slots = _mixed_slots()
    df = pd.DataFrame({
        "slot_datetime": slots,
        "Strompreis (Cent/kWh)": [
            16.0, 16.5, 16.2, 16.8, 17.0, 18.0, 19.0
        ],
    })
    axis = ChartSlotAxis.from_dataframe(df)
    line_x, line_y = _hourly_price_hv_xy(axis, df)
    assert line_x.iloc[0] == _dt(6, 0)
    assert line_x.iloc[1] == _dt(7, 0)
    assert line_y.iloc[0] == 16.0
    assert line_y.iloc[1] == 16.0
    price_changes = [
            index
            for index in range(1, len(line_y))
            if line_y.iloc[index] != line_y.iloc[index - 1]
        ]
    change_times = [line_x.iloc[index] for index in price_changes]
    assert _dt(7, 0) in change_times
    assert _dt(6, 15) not in change_times
    assert _dt(6, 30) not in change_times


def test_bar_widths_follow_slot_duration():
    slots = _mixed_slots()
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": slots}))
    widths = _bar_widths_ms(axis, 0, len(slots), 0.9)
    quarter_ms = 15 * 60 * 1000 * 0.9
    hour_ms = 60 * 60 * 1000 * 0.9
    assert widths[0] == quarter_ms
    assert widths[3] == quarter_ms
    assert widths[4] == hour_ms
    assert widths[5] == hour_ms
