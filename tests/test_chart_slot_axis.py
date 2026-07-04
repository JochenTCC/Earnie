"""Tests für zeitbasierte Chart-X-Achse."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from ui.charts import ChartSlotAxis

_TZ = ZoneInfo("Europe/Vienna")


def test_from_dataframe_requires_slot_datetime():
    with pytest.raises(ValueError, match="slot_datetime"):
        ChartSlotAxis.from_dataframe(pd.DataFrame({"Uhrzeit": ["01.01. 00:00"]}))


def test_infers_quarter_hour_step():
    start = datetime(2026, 7, 4, 9, 0, tzinfo=_TZ)
    slots = [start + timedelta(minutes=15 * index) for index in range(4)]
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": slots}))
    assert axis.step == timedelta(minutes=15)


def test_legacy_index_time_maps_slot_centers():
    start = datetime(2026, 7, 4, 10, 0, tzinfo=_TZ)
    axis = ChartSlotAxis.from_dataframe(
        pd.DataFrame({"slot_datetime": [start, start + timedelta(hours=1)]})
    )
    assert axis.legacy_index_time(0) == start + timedelta(minutes=30)
    assert axis.legacy_index_time(-0.5) == start