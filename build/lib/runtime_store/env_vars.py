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


def is_explicit_offline() -> bool:
    """True when EARNIE_OFFLINE / ENERGY_OPTIMIZER_OFFLINE is set to ``1``."""
    return is_truthy("OFFLINE")


def is_planning_offline_gated() -> bool:
    """
    Greenfield stays offline until Live-Konfiguration is saved
    (live scenario + entity refs in backtesting_scenarios.json).
    """
    from ui.setup_readiness import (
        is_live_configuration_complete,
        needs_planning_onboarding,
    )

    if not needs_planning_onboarding():
        return False
    return not is_live_configuration_complete()


def is_effective_offline() -> bool:
    """
    True when live Loxone paths must stay offline: explicit env flag or
    incomplete Live-Konfiguration during greenfield onboarding.
    """
    if is_explicit_offline():
        return True
    return is_planning_offline_gated()
