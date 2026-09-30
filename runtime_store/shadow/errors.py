"""Shadow Mode client errors (2.7.f)."""
from __future__ import annotations


class ShadowBackendAccessError(RuntimeError):
    """Backend I/O outside replayed transport primitives (programming error)."""


class ConfigReadOnlyError(RuntimeError):
    """Attempt to write shared config while Shadow Mode is active."""


class ShadowStartupError(RuntimeError):
    """Shadow refuses to start (missing runtime dir, bad feed, etc.)."""
