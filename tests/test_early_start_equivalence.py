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


# Network-fetch events the prefetch is meant to take off the cycle.
_PREFETCHED_EVENTS = {"day_ahead_fetch", "price_feature_refresh", "weather_fetch"}


# Ticks without a day-ahead publication between prefetch and cycle (the fake
# auction publishes at 12:52; then the cycle legitimately fetches once more).
_PREFETCH_TICKS = {
    "afternoon_hour": datetime(2026, 10, 15, 15, 0, tzinfo=TZ),
    "midnight": TICKS["midnight"],
}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(_PREFETCH_TICKS))
def test_prefetch_keeps_the_plan_and_takes_fetches_off_the_cycle(name, tmp_path):
    """Daemon order: prefetch ~14 min before the next start, then the early cycle.

    The cycle must plan and write the same as without prefetch, and must not hit
    the network for the prefetched inputs (warm, still-valid caches).
    """
    tick = _PREFETCH_TICKS[name]
    seed = seed_runtime(tmp_path, tick)
    start = shift(tick, -60)
    plain = run_from_seed(seed, tmp_path, "plain", frozen=start, tick=tick)
    warmed = run_from_seed(
        seed, tmp_path, "warmed", frozen=start, tick=tick, prefetch_at=shift(tick, -14 * 60)
    )
    assert warmed["prefetch"]["errors"] == []
    assert set(plain["cycle_events"]) & _PREFETCHED_EVENTS, "baseline fetched nothing"
    assert not set(warmed["cycle_events"]) & _PREFETCHED_EVENTS, warmed["cycle_events"]
    differences = diff(strip_volatile(plain), strip_volatile(warmed))
    assert not differences, "\n".join(differences[:30])
