"""Shadow Mode (S1 recorder + S2/S3 client).

Re-exports the core only (always shipped). Client functions are reached through
:mod:`runtime_store.shadow.hooks`, which the release image needs without the
client modules; see its docstring.
"""
from __future__ import annotations

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
from runtime_store.shadow.mode import is_shadow_config_readonly, is_shadow_mode

__all__ = [
    "ConfigReadOnlyError",
    "ShadowBackendAccessError",
    "ShadowStartupError",
    "flush_after_cycle",
    "flush_after_sampler",
    "is_feed_recording_enabled",
    "is_shadow_config_readonly",
    "is_shadow_mode",
]
