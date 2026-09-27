"""Shadow mode detection (env only)."""
from __future__ import annotations

from runtime_store.env_vars import is_truthy


def is_shadow_mode() -> bool:
    """True when ``EARNIE_SHADOW=1`` (never a config key)."""
    return is_truthy("SHADOW")
