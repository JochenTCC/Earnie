"""Shadow Mode helpers (S1 recorder in 2.6.o; client in 2.7.f)."""
from __future__ import annotations

from runtime_store.shadow.feed import (
    flush_after_cycle,
    flush_after_sampler,
    is_feed_recording_enabled,
)
from runtime_store.shadow.mode import is_shadow_mode
from runtime_store.shadow.superset import run_after_cycle as run_superset_after_cycle

__all__ = [
    "flush_after_cycle",
    "flush_after_sampler",
    "is_feed_recording_enabled",
    "is_shadow_mode",
    "run_superset_after_cycle",
]
