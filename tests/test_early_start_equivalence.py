"""EarlyStart: a cycle started before its tick writes what a cycle at the tick writes.

For each boundary tick T, one seed cycle runs at T-15 min; from copies of that
runtime, run A starts at T without early start (pre-P1 behaviour) and runs B
start at T-15 s and T-90 s with ``tick=T``. The wall clock is frozen globally
(``time_machine``), so any planning step that still reads the real clock
instead of ``planning_now`` shows up as a difference. Inputs are deterministic
and depend only on absolute time (``tests/early_start_runner.py``).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tests.early_start_equivalence import diff, run_from_seed, seed_runtime, shift, strip_volatile

pytest.importorskip("time_machine")

TZ = ZoneInfo("Europe/Vienna")
LEADS_SEC = (15, 90)

TICKS = {
    "quarter": datetime(2026, 10, 15, 12, 45, tzinfo=TZ),
    "hour": datetime(2026, 10, 15, 13, 0, tzinfo=TZ),
    "day_ahead_publish_hour": datetime(2026, 10, 15, 12, 0, tzinfo=TZ),
    "midnight": datetime(2026, 10, 16, 0, 0, tzinfo=TZ),
    "month": datetime(2026, 11, 1, 0, 0, tzinfo=TZ),
    "new_year": datetime(2027, 1, 1, 0, 0, tzinfo=TZ),
    "dst_spring_forward": datetime(2026, 3, 29, 3, 0, tzinfo=TZ),
    "dst_fall_back": datetime(2026, 10, 25, 3, 0, tzinfo=TZ),
}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(TICKS))
def test_early_start_plans_and_writes_like_a_cycle_at_the_tick(name, tmp_path):
    tick = TICKS[name]
    seed = seed_runtime(tmp_path, tick)
    at_tick = strip_volatile(run_from_seed(seed, tmp_path, "A", frozen=tick, tick=None))
    assert at_tick["writes"], "baseline cycle wrote no setpoints"
    assert at_tick["milp_calls"], "baseline cycle did not solve"

    for lead in LEADS_SEC:
        early = strip_volatile(
            run_from_seed(seed, tmp_path, f"B{lead}", frozen=shift(tick, -lead), tick=tick)
        )
        differences = diff(at_tick, early)
        assert not differences, (
            f"{name} lead {lead}s: early cycle differs from the cycle at the tick:\n"
            + "\n".join(differences[:30])
        )
