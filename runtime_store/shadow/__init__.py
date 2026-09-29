"""Shadow Mode helpers (S1 recorder + S2/S3 client)."""
from __future__ import annotations

from runtime_store.shadow.cycle import (
    consume_optimize_trigger,
    feed_health,
    feed_lag,
    wait_for_prod_cycle,
)
from runtime_store.shadow.errors import (
    ConfigReadOnlyError,
    ShadowBackendAccessError,
    ShadowStartupError,
)
from runtime_store.shadow.feed import (
    flush_after_cycle,
    flush_after_sampler,
    is_feed_recording_enabled,
)
from runtime_store.shadow.mode import is_shadow_mode
from runtime_store.shadow.startup import (
    ensure_shadow_startup,
    refuse_shadow_startup_or_exit,
)
from runtime_store.shadow.superset import run_after_cycle as run_superset_after_cycle
from runtime_store.shadow.writes import (
    block_write_if_shadow,
    log_would_write,
    read_shadow_writes,
)

__all__ = [
    "ConfigReadOnlyError",
    "ShadowBackendAccessError",
    "ShadowStartupError",
    "block_write_if_shadow",
    "consume_optimize_trigger",
    "ensure_shadow_startup",
    "feed_health",
    "feed_lag",
    "flush_after_cycle",
    "flush_after_sampler",
    "is_feed_recording_enabled",
    "is_shadow_mode",
    "log_would_write",
    "read_shadow_writes",
    "refuse_shadow_startup_or_exit",
    "run_superset_after_cycle",
    "wait_for_prod_cycle",
]
