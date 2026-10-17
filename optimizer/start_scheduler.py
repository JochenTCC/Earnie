"""Early-start lead for regular Live cycles (EarlyStart P1).

Pure functions over the punctuality records of ``runtime/cycle_stats.jsonl``
(``runtime_store.cycle_duration_stats``): how many seconds before the
quarter-hour tick the next regular cycle starts so its plan is ready at the
tick. No clock, no I/O — the daemon loop in ``main.py`` loads the records and
schedules the start.

Goal: setpoints with minimal age at the tick, in both directions — a plan
ready long before the tick is built on old telemetry, a plan ready after it
leaves the slot on old setpoints. The lead that minimises the mean absolute
gap |ready − tick| is the **median** time to plan, so:

Lead = clamp(median(time to plan), 15 s, 90 s), i.e. the cycle starts
between T−90 s and T−15 s; with fewer than ``MIN_SAMPLES`` records (new
platform) the lead is 60 s. Above 90 s the start is not moved further forward
(``capped``); the daemon warns.
Spec: ``docs/dev/done/early-start-scheduling.md`` §5.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

EARLY_START_ENV = "EARNIE_EARLY_START"

LEAD_MIN_SEC = 15.0
LEAD_MAX_SEC = 90.0
# A plan ready later than tick + this many seconds is warned about again.
LATE_WARN_SEC = 90.0

WINDOW_CYCLES = 96  # one day of regular cycles
MIN_SAMPLES = 8  # below: bootstrap with BOOTSTRAP_LEAD_SEC

# Until the platform has measurements.
BOOTSTRAP_LEAD_SEC = 60.0

REASON_OFF = "off"
REASON_BOOTSTRAP = "bootstrap"
REASON_ESTIMATE = "median"
REASON_MIN = "min"
REASON_CAPPED = "capped"


@dataclass(frozen=True)
class LeadDecision:
    lead_sec: float
    reason: str
    estimate_sec: float | None
    samples: int

    @property
    def capped(self) -> bool:
        return self.reason == REASON_CAPPED


def early_start_enabled() -> bool:
    """``EARNIE_EARLY_START``: ``on`` (default, also unset) or ``off``."""
    raw = os.environ.get(EARLY_START_ENV)
    if raw is None or not raw.strip():
        return True
    value = raw.strip().lower()
    if value == "on":
        return True
    if value == "off":
        return False
    raise ValueError(f"{EARLY_START_ENV}={raw!r}: erlaubt sind 'on' oder 'off'.")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def time_to_plan_sec(record: dict) -> float | None:
    """Seconds from cycle start until the plan was ready (writes as proxy for old records)."""
    started = _parse(record.get("started_at"))
    ready = _parse(record.get("ready_at")) or _parse(record.get("writes_done_at"))
    if started is None or ready is None:
        return None
    return (ready - started).total_seconds()


def plan_durations(records: list[dict], *, platform: str | None = None) -> list[float]:
    """Time-to-plan of the last ``WINDOW_CYCLES`` regular cycles that wrote setpoints.

    Records from another compute platform are ignored (a new host starts fresh).
    ``cold_start`` records are ignored: their time to plan includes process
    import and the power-archive load, not a steady cycle.
    """
    out: list[float] = []
    for row in records:
        if row.get("trigger") != "quarter_hour" or row.get("outcome") != "ok":
            continue
        if platform is not None and row.get("platform") != platform:
            continue
        if "cold_start" in (row.get("events") or []):
            continue
        value = time_to_plan_sec(row)
        if value is not None and value >= 0:
            out.append(value)
    return out[-WINDOW_CYCLES:]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def decide_lead(
    records: list[dict], *, platform: str | None = None, enabled: bool = True
) -> LeadDecision:
    """Lead for the next regular cycle from the recorded time-to-plan."""
    if not enabled:
        return LeadDecision(0.0, REASON_OFF, None, 0)
    durations = plan_durations(records, platform=platform)
    if len(durations) < MIN_SAMPLES:
        return LeadDecision(BOOTSTRAP_LEAD_SEC, REASON_BOOTSTRAP, None, len(durations))
    estimate = round(_median(durations), 1)
    if estimate > LEAD_MAX_SEC:
        return LeadDecision(LEAD_MAX_SEC, REASON_CAPPED, estimate, len(durations))
    if estimate < LEAD_MIN_SEC:
        return LeadDecision(LEAD_MIN_SEC, REASON_MIN, estimate, len(durations))
    return LeadDecision(math.ceil(estimate), REASON_ESTIMATE, estimate, len(durations))


def next_regular_start(now: datetime, lead_sec: float) -> tuple[datetime, datetime]:
    """``(tick, start_at)`` of the next regular cycle.

    ``tick`` is the next quarter-hour boundary after ``now``; ``start_at`` is
    ``lead_sec`` before it, but never before ``now`` (a long previous cycle
    that ends inside the lead window starts the next one at once).
    """
    from optimizer.schedule import QUARTER_HOUR_MINUTES, quarter_hour_slot_start

    tick = quarter_hour_slot_start(now) + timedelta(minutes=QUARTER_HOUR_MINUTES)
    start_at = max(now, tick - timedelta(seconds=float(lead_sec)))
    return tick, start_at
