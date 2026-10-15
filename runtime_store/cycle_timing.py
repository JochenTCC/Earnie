"""Env-gated live-cycle phase timing and optional cProfile dumps.

Enable with ``EARNIE_CYCLE_TIMING=1`` (JSONL under ``runtime/timing/``).
Optional ``EARNIE_CYCLE_PROFILE=1`` writes ``runtime/profile/cycle_*.prof``
(and a short top-30 pstats text). Keep profile on for only 1–2 cycles.
"""
from __future__ import annotations

import cProfile
import json
import logging
import pstats
import time
from contextlib import contextmanager
from contextvars import ContextVar
from io import StringIO
from pathlib import Path
from typing import Iterator

from runtime_store.env_vars import is_truthy
from runtime_store.persist_paths import runtime_path

logger = logging.getLogger("cycle_timing")

_TIMING_DIR = "timing"
_PROFILE_DIR = "profile"
_JSONL_NAME = "cycles.jsonl"
_TOP_N_PSTATS = 30

_active: ContextVar["CycleTimer | None"] = ContextVar("earnie_cycle_timer", default=None)


def timing_enabled() -> bool:
    return is_truthy("CYCLE_TIMING")


def profile_enabled() -> bool:
    return is_truthy("CYCLE_PROFILE")


def timing_dir() -> Path:
    return Path(runtime_path(_TIMING_DIR))


def profile_dir() -> Path:
    return Path(runtime_path(_PROFILE_DIR))


def jsonl_path() -> Path:
    return timing_dir() / _JSONL_NAME


class CycleTimer:
    """Accumulates named wall-clock phases for one optimization cycle."""

    def __init__(self, *, slot_key: str | None = None) -> None:
        self.enabled = timing_enabled()
        self.profile = profile_enabled()
        self.slot_key = slot_key or ""
        self.phases: dict[str, float] = {}
        self._wall_t0 = time.perf_counter()
        self._profiler: cProfile.Profile | None = None
        self._token = None

    def activate(self) -> None:
        self._token = _active.set(self)
        if self.profile:
            self._profiler = cProfile.Profile()
            self._profiler.enable()

    def deactivate(self) -> None:
        if self._profiler is not None:
            self._profiler.disable()
        if self._token is not None:
            _active.reset(self._token)
            self._token = None

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.phases[name] = self.phases.get(name, 0.0) + (
                time.perf_counter() - t0
            )

    def finish(self) -> dict | None:
        """Write JSONL / profile dumps when enabled; always deactivate."""
        try:
            return self._finish_writes()
        finally:
            self.deactivate()

    def _finish_writes(self) -> dict | None:
        if not self.enabled and self._profiler is None:
            return None
        total_sec = time.perf_counter() - self._wall_t0
        if self.enabled:
            self.phases["total"] = total_sec
        payload = {
            "slot": self.slot_key,
            "phases_sec": {
                k: round(v, 4) for k, v in sorted(self.phases.items())
            },
            "profile": bool(self._profiler is not None),
        }
        if self.enabled:
            self._append_jsonl(payload)
            self._log_summary(payload)
        if self._profiler is not None:
            self._dump_profile()
        return payload

    def _append_jsonl(self, payload: dict) -> None:
        path = jsonl_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("cycle_timing: JSONL write failed: %s", exc)

    def _log_summary(self, payload: dict) -> None:
        phases = payload.get("phases_sec") or {}
        ranked = sorted(
            ((k, v) for k, v in phases.items() if k != "total"),
            key=lambda item: item[1],
            reverse=True,
        )
        top = ", ".join(f"{k}={v:.3f}s" for k, v in ranked[:5])
        logger.info(
            "cycle_timing: total=%.3fs slot=%s | %s",
            float(phases.get("total") or 0.0),
            payload.get("slot") or "?",
            top or "(no phases)",
        )

    def _dump_profile(self) -> None:
        assert self._profiler is not None
        slot = self.slot_key or "unknown"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in slot)
        out_dir = profile_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            prof_path = out_dir / f"cycle_{safe}.prof"
            self._profiler.dump_stats(str(prof_path))
            text_path = out_dir / f"cycle_{safe}_top{_TOP_N_PSTATS}.txt"
            stream = StringIO()
            stats = pstats.Stats(self._profiler, stream=stream)
            stats.sort_stats("cumulative")
            stats.print_stats(_TOP_N_PSTATS)
            text_path.write_text(stream.getvalue(), encoding="utf-8")
            logger.info(
                "cycle_timing: cProfile dumped %s (+ %s); unset "
                "EARNIE_CYCLE_PROFILE after 1–2 cycles",
                prof_path.name,
                text_path.name,
            )
        except OSError as exc:
            logger.warning("cycle_timing: profile dump failed: %s", exc)


@contextmanager
def cycle_session(*, slot_key: str | None = None) -> Iterator[CycleTimer]:
    """Activate a timer for one ``main()`` cycle; finish on exit."""
    timer = CycleTimer(slot_key=slot_key)
    timer.activate()
    try:
        yield timer
    finally:
        timer.finish()


@contextmanager
def record_phase(name: str) -> Iterator[None]:
    """Record into the active cycle timer; no-op when timing is off."""
    timer = _active.get()
    if timer is None or not timer.enabled:
        yield
        return
    with timer.phase(name):
        yield


def get_active_timer() -> CycleTimer | None:
    return _active.get()
