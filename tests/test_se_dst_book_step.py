"""Regression: SE sunrise steps across DST changes (MILP slots vs. booked slots).

Since ``dc192f00`` the Live planning grid (``hourly_slots_inclusive``) steps in real
time, while the SE books on naive wall-clock slots of its historical data. A sunrise
step over 2026-03-29 then looked for the non-existent 02:xx slots in the MILP matrix
("Sunrise-Overlay: Buchungs-Slots fehlen in der MILP-Matrix"), and one over 2025-10-26
got the repeated 02:xx hour twice under the same naive key ("Sunrise-Schritt: erwartet
92 Slots, gefunden 96"). Every SE year run that contains a DST change aborted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from simulation.backtesting_horizon import (
    naive_backtesting_slot,
    resolve_ready_by_sunrise_step,
    wall_clock_slots_inclusive,
)

_LAT = 47.40
_LON = 9.74
_TZ = "Europe/Vienna"


@pytest.mark.parametrize(
    "ready_by",
    [
        datetime(2026, 3, 29, 7, 0),  # book [SA 03-28, SA 03-29) holds the spring night
        datetime(2026, 3, 30, 7, 0),  # MILP SA0 on 03-28 spans the spring night
        datetime(2025, 10, 26, 12, 0),  # book holds the autumn night
        datetime(2025, 10, 27, 7, 0),  # MILP SA0 on 10-25 spans the autumn night
    ],
)
def test_book_slots_are_milp_slots_on_dst_days(ready_by):
    step = resolve_ready_by_sunrise_step(ready_by, _LAT, _LON, _TZ)
    milp = [naive_backtesting_slot(slot) for slot in step.milp_slots]
    book = [naive_backtesting_slot(slot) for slot in step.book_slots]

    # Naive keys are unique: the SE keys matrix rows, prices and cons_data by them.
    assert len(milp) == len(set(milp))
    missing = sorted(set(book) - set(milp))
    assert not missing, f"booked slots missing in the MILP grid: {missing[:4]}"
    # Book is a contiguous block of the MILP grid starting at SA1.
    assert milp[step.sa1_index : step.sa1_index + len(book)] == book
    # Both grids step 15 wall-clock minutes, like the naive historical data.
    quarter = timedelta(minutes=15)
    assert all(b - a == quarter for a, b in zip(milp, milp[1:]))


@pytest.mark.parametrize(
    "start, end",
    [
        # Fixed offsets (the Live grid's slot form) would step real time.
        (
            datetime(2026, 3, 28, 7, 0, tzinfo=timezone(timedelta(hours=1))),
            datetime(2026, 3, 30, 7, 0, tzinfo=timezone(timedelta(hours=2))),
        ),
        # Two zones.
        (
            datetime(2026, 3, 28, 7, 0, tzinfo=ZoneInfo(_TZ)),
            datetime(2026, 3, 30, 7, 0, tzinfo=ZoneInfo("UTC")),
        ),
    ],
)
def test_wall_clock_grid_rejects_non_zone_bounds(start, end):
    with pytest.raises(ValueError, match="ZoneInfo"):
        wall_clock_slots_inclusive(start, end)


def test_wall_clock_grid_keeps_wall_clock_on_spring_day():
    zone = ZoneInfo(_TZ)
    slots = wall_clock_slots_inclusive(
        datetime(2026, 3, 29, 0, 0, tzinfo=zone), datetime(2026, 3, 30, 0, 0, tzinfo=zone)
    )
    assert len(slots) == 97  # 96 wall-clock quarter hours incl. 02:xx, plus the end slot
