"""TE5 (Edibert P7 S5): the next month near a month boundary is taken in the planning time zone."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import time_machine

import config
from ui.pages.scenario_editor_tariffs import _next_month_in_planning_tz


@pytest.mark.parametrize(
    "utc_now,expected",
    [
        # 23:30 in Vienna on 31 Oct (CET, UTC+1): still October locally and in UTC.
        (datetime(2026, 10, 31, 22, 30, tzinfo=timezone.utc), (2026, 11)),
        # 00:30 in Vienna on 1 Nov: November locally, still October in UTC.
        (datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc), (2026, 12)),
        # 00:30 in Vienna on 1 Jan: the year rolls over locally only.
        (datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc), (2027, 2)),
    ],
)
def test_te5_next_month_in_the_planning_time_zone(monkeypatch, utc_now, expected):
    monkeypatch.setattr(config.CONFIG, "PLANNING_TIMEZONE", "Europe/Vienna")
    with time_machine.travel(utc_now, tick=False):
        assert _next_month_in_planning_tz() == expected
