"""Helpers for the EarlyStart equivalence test (A: at the tick, B: early with lead).

Each run is a fresh ``python -m tests.early_start_runner`` subprocess on a copy
of the same seed runtime, so process-wide caches cannot leak between A and B.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Keys that legitimately differ between runs (wall-clock stamps of the run itself).
_VOLATILE_KEYS = frozenset(
    {
        "completed_at",
        "written_at",
        "timestamp",
        "run_started_at",
        "hold_from",
        "recorded_at",
        "fetched_at",
        "duration_sec",
        "cycle_events",
        "prefetch",
    }
)


def shift(moment: datetime, seconds: float) -> datetime:
    """``moment + seconds`` in absolute time (wall-clock arithmetic breaks at DST)."""
    from datetime import timezone

    return (moment.astimezone(timezone.utc) + timedelta(seconds=seconds)).astimezone(moment.tzinfo)


# Each runner imports the full app and solves a MILP; under ``-n auto`` all
# xdist workers would start runners at once and exhaust memory (HiGHS
# "bad allocation"). A small cross-process semaphore caps concurrent runners.
_MAX_CONCURRENT_RUNNERS = 2
_SLOT_STALE_SEC = 600


@contextmanager
def _runner_slot() -> Iterator[None]:
    lock_dir = Path(tempfile.gettempdir())
    while True:
        for index in range(_MAX_CONCURRENT_RUNNERS):
            lock = lock_dir / f"earnie_early_start_runner_{index}.lock"
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > _SLOT_STALE_SEC:
                        lock.unlink(missing_ok=True)  # left behind by a killed run
                except OSError:
                    pass
                continue
            except PermissionError:
                # Windows: O_EXCL on a lock another worker just unlinked (still
                # delete-pending) raises EACCES instead of EEXIST -> slot busy.
                if sys.platform != "win32":
                    raise
                continue
            os.close(fd)
            try:
                yield
            finally:
                lock.unlink(missing_ok=True)
            return
        time.sleep(0.2)


def run_cycle(
    runtime: Path,
    out: Path,
    *,
    frozen: datetime,
    tick: datetime | None,
    prefetch_at: datetime | None = None,
) -> dict:
    with _runner_slot():
        return _run_cycle(runtime, out, frozen=frozen, tick=tick, prefetch_at=prefetch_at)


def _run_cycle(
    runtime: Path,
    out: Path,
    *,
    frozen: datetime,
    tick: datetime | None,
    prefetch_at: datetime | None,
) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "tests.early_start_runner",
        "--runtime",
        str(runtime),
        "--frozen",
        frozen.isoformat(),
        "--out",
        str(out),
    ]
    if tick is not None:
        cmd += ["--tick", tick.isoformat()]
    if prefetch_at is not None:
        cmd += ["--prefetch-at", prefetch_at.isoformat()]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"runner failed ({frozen}, tick={tick}):\n{proc.stderr[-4000:]}")
    return json.loads(out.read_text(encoding="utf-8"))


def seed_runtime(base: Path, tick: datetime) -> Path:
    """Runtime after one regular cycle a slot earlier (profiles, caches, states)."""
    seed = base / "seed"
    seed.mkdir(parents=True)
    run_cycle(seed, base / "seed.json", frozen=shift(tick, -15 * 60), tick=None)
    return seed


def run_from_seed(
    seed: Path,
    base: Path,
    name: str,
    *,
    frozen: datetime,
    tick: datetime | None,
    prefetch_at: datetime | None = None,
) -> dict:
    runtime = base / name
    shutil.copytree(seed, runtime)
    return run_cycle(
        runtime, base / f"{name}.json", frozen=frozen, tick=tick, prefetch_at=prefetch_at
    )


def strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_volatile(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, list):
        return [strip_volatile(v) for v in value]
    return value


def diff(a: Any, b: Any, path: str = "") -> list[str]:
    """Human-readable differences (first few per branch)."""
    out: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                out.append(f"{path}/{key}: only in {'B' if key not in a else 'A'}")
                continue
            out += diff(a[key], b[key], f"{path}/{key}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: len {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
            if len(out) > 40:
                break
    elif a != b:
        out.append(f"{path}: {a!r} != {b!r}")
    return out
