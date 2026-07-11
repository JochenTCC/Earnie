"""Environment variables: EARNIE_* canonical, ENERGY_OPTIMIZER_* legacy fallback."""
from __future__ import annotations

import os


def read_env(suffix: str) -> str:
    """Read ``EARNIE_{suffix}`` with ``ENERGY_OPTIMIZER_{suffix}`` fallback."""
    for prefix in ("EARNIE_", "ENERGY_OPTIMIZER_"):
        raw = os.environ.get(f"{prefix}{suffix}")
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


def read_env_or(suffix: str, default: str) -> str:
    value = read_env(suffix)
    return value if value else default


def is_truthy(suffix: str) -> bool:
    return read_env(suffix) == "1"
