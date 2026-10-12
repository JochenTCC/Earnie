"""Shadow mode detection (env only)."""
from __future__ import annotations

from pathlib import Path

from runtime_store.env_vars import is_truthy


def is_shadow_mode() -> bool:
    """True when ``EARNIE_SHADOW=1`` (never a config key)."""
    return is_truthy("SHADOW")


def is_shadow_config_readonly() -> bool:
    """
    True when Shadow must not mutate this process's ``config_dir()``.

    Classic shared-config Shadow keeps the feed under ``{config}/shadow_feed``
    → read-only. When ``EARNIE_SHADOW_FEED_PATH`` (or equivalent) points the
    feed **outside** this config tree, the local env is a private Shadow
    config and may be written.
    """
    if not is_shadow_mode():
        return False
    from runtime_store.persist_paths import config_dir
    from runtime_store.shadow.feed import feed_dir

    try:
        cfg = Path(config_dir()).resolve()
        feed = feed_dir().resolve()
    except OSError:
        return True
    try:
        feed.relative_to(cfg)
    except ValueError:
        return False
    return True
