"""A generic flex consumer delivers in whole blocks: slots that cannot host one are no capacity.

Found in the viability study (packs_stufe1d_app): the first SE book ran 00:00 to 08:00, the
dishwasher's CSV run started 07:00 (2.5 h), so the book target was 0.36 kWh with only four
eligible slots for a ten-slot block. The strict solve was infeasible and the whole step fell
back to the automatic mode.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from optimizer.milp_consumer_delivery import (
    deliverable_indices,
    delivery_constraint_diagnostics,
    generic_block_slots,
)

DISHWASHER = {
    "id": "geschirrspueler",
    "name": "Geschirrspüler",
    "type": "generic",
    "nominal_power_kw": 0.36,
    "min_power_kw": 0.36,
    "min_on_quarterhours": 10,
    "daily_target_kwh": 0.0,
    "signal_type": "binary",
    "optimizer_enabled": True,
    "generic_flex_window": {"start_hour": 14, "start_shift_h": 7.0, "duration_h": 2.5},
}


def _quarter_hour_matrix(start: datetime, slots: int) -> list[dict]:
    rows = []
    for index in range(slots):
        slot = start + timedelta(minutes=15 * index)
        rows.append({"hour": slot.hour, "date": slot.date(), "slot_datetime": slot})
    return rows


def test_block_slots_need_a_contiguous_run_of_one_block():
    assert generic_block_slots([28, 29, 30, 31], 10) == []
    assert generic_block_slots(list(range(12)) + [20, 21], 10) == list(range(12))
    assert generic_block_slots([5, 3, 4, 9], 3) == [3, 4, 5]
    assert generic_block_slots([], 10) == []
    assert generic_block_slots([7, 8], 1) == [7, 8]


def test_deliverable_indices_respect_book_and_blocks():
    eligible = list(range(28, 60))  # 07:00 to 14:45 of a day that starts at index 0
    assert deliverable_indices(DISHWASHER, eligible, book_indices=list(range(32))) == []
    assert deliverable_indices(DISHWASHER, eligible, book_indices=list(range(48))) == list(range(28, 48))
    assert deliverable_indices(DISHWASHER, eligible) == eligible
    fixed = {"id": "x", "nominal_power_kw": 1.0, "min_on_quarterhours": 10}
    assert deliverable_indices(fixed, [28, 29], book_indices=[29, 30]) == [29]


def test_first_book_until_eight_cannot_host_the_dishwasher_block():
    matrix = _quarter_hour_matrix(datetime(2025, 1, 1, 0, 0), 32)  # 00:00 .. 07:45
    diagnostics = delivery_constraint_diagnostics(
        matrix, {"geschirrspueler": 0.36}, list(range(32)), {}, [DISHWASHER]
    )
    entry = diagnostics["geschirrspueler"]
    assert entry["eligible_count"] == 4
    assert entry["deliverable_count"] == 0
    assert entry["max_deliverable_kwh"] == 0.0
    assert entry["effective_target_kwh"] == 0.0


def test_a_full_day_hosts_the_block_and_keeps_the_target():
    matrix = _quarter_hour_matrix(datetime(2025, 1, 2, 8, 0), 96)  # 08:00 .. 07:45 next day
    diagnostics = delivery_constraint_diagnostics(
        matrix, {"geschirrspueler": 0.36}, list(range(96)), {}, [DISHWASHER]
    )
    entry = diagnostics["geschirrspueler"]
    # 08:00 .. 23:45 = 64 slots in one run; the 07:00 .. 07:45 run of the next morning is too short.
    assert entry["eligible_count"] == 68
    assert entry["deliverable_count"] == 64
    assert entry["effective_target_kwh"] == 0.36
