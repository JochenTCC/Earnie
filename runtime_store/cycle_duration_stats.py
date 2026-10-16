"""Always-on cycle duration, event and punctuality log (EarlyStart P0).

One JSON line per ``main()`` cycle in ``runtime/cycle_stats.jsonl`` (rolling,
``RETENTION_DAYS``). Records when the daemon woke up, when the cycle started,
when the plan was ready (``ready_at``, before holding for the tick), when
setpoints were written (``writes_done_at``) and how late that was against the
quarter-hour tick of the slot (``late_by_sec``). With early start (P1) the
cycle starts ``lead_sec`` before its tick; wake/start delays are measured
against that planned start. Data modules report network fetches via
:func:`record_event`.

Independent of the env-gated profiling in ``runtime_store.cycle_timing``.
Spec: ``docs/spec/early-start-scheduling.md`` §5.1, §5.2, §5.6.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from runtime_store.persist_paths import runtime_path

logger = logging.getLogger("cycle_stats")

STATS_FILENAME = "cycle_stats.jsonl"
RETENTION_DAYS = 7
# Setpoints written up to this many seconds after the tick still count as on time.
ON_TIME_TOLERANCE_SEC = 2.0
SUMMARY_WINDOWS = (("24 h", timedelta(hours=24)), ("7 d", timedelta(days=7)))

OUTCOME_OK = "ok"
OUTCOME_NO_WRITES = "no_writes"
OUTCOME_ERROR = "error"

EVENT_COLD_START = "cold_start"
EVENT_PV_FORECAST_FETCH = "pv_forecast_fetch"
EVENT_WEATHER_FETCH = "weather_fetch"
EVENT_PRICE_FEATURE_REFRESH = "price_feature_refresh"
EVENT_DAY_AHEAD_FETCH = "day_ahead_fetch"

# Same label as optimizer.run_trigger.TRIGGER_QUARTER_HOUR. Not imported: data modules
# import this module at top level, and the optimizer package import is heavy.
TRIGGER_QUARTER_HOUR = "quarter_hour"

_active: ContextVar["CycleStats | None"] = ContextVar("earnie_cycle_stats", default=None)


def stats_path() -> Path:
    return Path(runtime_path(STATS_FILENAME))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="milliseconds")


def _seconds(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None:
        return None
    return round((later - earlier).total_seconds(), 3)


def _cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def _solver_label() -> str:
    from importlib import metadata

    from optimizer.cbc_solver import resolve_milp_solver

    backend = resolve_milp_solver()
    dist = "highspy" if backend == "highs" else "pulp"
    try:
        return f"{backend} {metadata.version(dist)}"
    except metadata.PackageNotFoundError:
        return f"{backend} (version unknown)"


@lru_cache(maxsize=1)
def platform_info() -> dict:
    """Hardware/runtime fingerprint; ``id`` changes when the compute platform does.

    Hostname is left out on purpose: Docker gives every recreated container a new one.
    The Earnie version is recorded per cycle, not in the fingerprint.
    """
    info = {
        "cpu": _cpu_model(),
        "cpus": os.cpu_count(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "solver": _solver_label(),
    }
    digest = hashlib.sha1(
        json.dumps(info, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    return {"id": digest, **info}


@dataclass
class CycleStats:
    """Timestamps and events of one optimization cycle."""

    trigger: str
    started_at: datetime
    woke_at: datetime | None = None
    tick: datetime | None = None
    lead_sec: float = 0.0
    ready_at: datetime | None = None
    writes_done_at: datetime | None = None
    horizon_slots: int | None = None
    events: list[str] = field(default_factory=list)
    # True only when the caller passed a tick this cycle was planned for.
    scheduled: bool = False

    def __post_init__(self) -> None:
        # Captured before the slot fill-in below: an omitted tick is not a
        # punctuality sample (first cycle after start, early start off, stale tick).
        self.scheduled = self.tick is not None
        if self.tick is None:
            from optimizer.schedule import quarter_hour_slot_start

            # No early start: the cycle computes for the slot it runs in.
            self.tick = quarter_hour_slot_start(self.started_at)

    @property
    def planned_start(self) -> datetime:
        return self.tick - timedelta(seconds=self.lead_sec)

    @property
    def regular(self) -> bool:
        return self.trigger == TRIGGER_QUARTER_HOUR

    def note_event(self, name: str) -> None:
        if name not in self.events:
            self.events.append(name)

    def mark_ready(self, at: datetime | None = None) -> None:
        self.ready_at = at or datetime.now()

    def mark_writes_done(self, at: datetime | None = None) -> None:
        self.writes_done_at = at or datetime.now()

    def to_record(self, *, outcome: str, finished_at: datetime, version: str) -> dict:
        late_by = _seconds(self.writes_done_at, self.tick)
        on_time = None
        if self.regular and self.scheduled and late_by is not None:
            on_time = late_by <= ON_TIME_TOLERANCE_SEC
        return {
            "tick": _iso(self.tick),
            "trigger": self.trigger,
            "outcome": outcome,
            "lead_sec": self.lead_sec,
            "woke_at": _iso(self.woke_at),
            "started_at": _iso(self.started_at),
            "ready_at": _iso(self.ready_at),
            "writes_done_at": _iso(self.writes_done_at),
            "finished_at": _iso(finished_at),
            "wake_delay_sec": _seconds(self.woke_at, self.planned_start),
            "start_delay_sec": _seconds(self.started_at, self.planned_start),
            "duration_sec": _seconds(finished_at, self.started_at),
            "ready_by_sec": _seconds(self.ready_at, self.tick),
            "late_by_sec": late_by,
            "on_time": on_time,
            "events": list(self.events),
            "clock_skew_sec": _clock_skew_sec(),
            "horizon_slots": self.horizon_slots,
            "version": version,
            "platform": platform_info()["id"],
        }


class _EventCollector:
    """Collects ``record_event`` calls outside a cycle (prefetch)."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def note_event(self, name: str) -> None:
        if name not in self.events:
            self.events.append(name)


@contextmanager
def collect_events() -> Iterator[list[str]]:
    """Gather data-module events (network fetches) for a block outside a cycle."""
    collector = _EventCollector()
    token = _active.set(collector)  # type: ignore[arg-type]
    try:
        yield collector.events
    finally:
        _active.reset(token)


def _clock_skew_sec() -> float | None:
    """Host clock offset vs. HTTP Date headers (+ = local clock behind); warns if large."""
    from runtime_store import clock_skew

    estimate = clock_skew.current_estimate()
    clock_skew.maybe_warn(estimate)
    return None if estimate is None else estimate.offset_sec


def record_event(name: str) -> None:
    """Note a known slow-path event (e.g. network fetch) on the running cycle."""
    stats = _active.get()
    if stats is not None:
        stats.note_event(name)


def mark_ready() -> None:
    """Plan computed; the cycle may now hold until its tick before writing."""
    stats = _active.get()
    if stats is not None:
        stats.mark_ready()


def mark_writes_done() -> None:
    stats = _active.get()
    if stats is not None:
        stats.mark_writes_done()


def set_horizon_slots(count: int) -> None:
    stats = _active.get()
    if stats is not None:
        stats.horizon_slots = int(count)


@contextmanager
def cycle_stats_session(
    *,
    trigger: str,
    version: str,
    woke_at: datetime | None = None,
    cold_start: bool = False,
    tick: datetime | None = None,
    lead_sec: float = 0.0,
) -> Iterator[CycleStats]:
    """Track one ``main()`` cycle and append its record when it ends.

    ``tick`` is the slot start an early-started cycle plans for (``None``: the
    slot the cycle starts in); ``lead_sec`` is how early it was scheduled.
    """
    stats = CycleStats(
        trigger=trigger,
        started_at=datetime.now(),
        woke_at=woke_at,
        tick=tick,
        lead_sec=float(lead_sec),
    )
    if cold_start:
        stats.note_event(EVENT_COLD_START)
    token = _active.set(stats)
    outcome = OUTCOME_ERROR
    try:
        yield stats
        outcome = OUTCOME_OK if stats.writes_done_at is not None else OUTCOME_NO_WRITES
    finally:
        _active.reset(token)
        record = stats.to_record(
            outcome=outcome, finished_at=datetime.now(), version=version
        )
        append_record(record)
        _log_cycle(record)


def append_record(record: dict, *, path: Path | None = None) -> None:
    target = path or stats_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        _prune_if_due(target, now=datetime.fromisoformat(record["tick"]))
    except OSError as exc:
        logger.warning("cycle_stats: write to %s failed: %s", target, exc)


def load_records(path: Path | None = None) -> list[dict]:
    source = path or stats_path()
    if not source.is_file():
        return []
    rows: list[dict] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _prune_if_due(path: Path, *, now: datetime) -> None:
    """Drop records older than ``RETENTION_DAYS``; rewrite at most once per day."""
    with path.open("r", encoding="utf-8") as fh:
        first = fh.readline().strip()
    if not first:
        return
    oldest = datetime.fromisoformat(json.loads(first)["tick"])
    if now - oldest <= timedelta(days=RETENTION_DAYS + 1):
        return
    cutoff = now - timedelta(days=RETENTION_DAYS)
    kept = [
        row for row in load_records(path)
        if datetime.fromisoformat(row["tick"]) >= cutoff
    ]
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in kept),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def punctuality_summary(
    records: list[dict], *, now: datetime, window: timedelta
) -> dict:
    """On-time rate and lateness of regular cycles that wrote setpoints in ``window``."""
    cutoff = now - window
    late = [
        float(row["late_by_sec"])
        for row in records
        if row.get("on_time") is not None
        and datetime.fromisoformat(row["tick"]) >= cutoff
    ]
    if not late:
        return {"cycles": 0, "on_time": 0, "p50_late_sec": None, "p95_late_sec": None}
    return {
        "cycles": len(late),
        "on_time": sum(1 for sec in late if sec <= ON_TIME_TOLERANCE_SEC),
        "p50_late_sec": _quantile(late, 0.5),
        "p95_late_sec": _quantile(late, 0.95),
    }


def _fmt_sec(value: float | None) -> str:
    return "–" if value is None else f"{value:+.0f} s"


def _log_cycle(record: dict) -> None:
    if record["trigger"] != TRIGGER_QUARTER_HOUR:
        logger.info(
            "cycle_stats: außerplanmäßiger Lauf (%s) – Dauer %.0f s, Ergebnis %s",
            record["trigger"],
            float(record["duration_sec"] or 0.0),
            record["outcome"],
        )
        return
    parts = [f"Tick {record['tick'][11:16]}"]
    lead = float(record.get("lead_sec") or 0.0)
    if lead > 0:
        parts.append(f"Vorlauf {lead:.0f} s")
    parts += [
        f"Weckzeit {_fmt_sec(record['wake_delay_sec'])}",
        f"Start {_fmt_sec(record['start_delay_sec'])}",
        f"Plan fertig {_fmt_sec(record.get('ready_by_sec'))}",
        f"Sollwerte {_fmt_sec(record['late_by_sec'])}",
        f"Dauer {float(record['duration_sec'] or 0.0):.0f} s",
    ]
    if record["outcome"] != OUTCOME_OK:
        parts.append(f"Ergebnis {record['outcome']}")
    if record["events"]:
        parts.append("Ereignisse " + ",".join(record["events"]))
    try:
        records = load_records()
    except (OSError, ValueError) as exc:
        logger.warning("cycle_stats: summary read failed: %s", exc)
        records = []
    now = datetime.fromisoformat(record["tick"])
    for label, window in SUMMARY_WINDOWS:
        summary = punctuality_summary(records, now=now, window=window)
        if summary["cycles"]:
            parts.append(
                f"{label}: {summary['on_time']}/{summary['cycles']} pünktlich, "
                f"P95 {_fmt_sec(summary['p95_late_sec'])}"
            )
    logger.info("Pünktlichkeit: %s", " | ".join(parts))
