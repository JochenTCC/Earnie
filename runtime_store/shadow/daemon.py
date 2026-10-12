"""Shadow / Prod daemon loop glue extracted from ``main.py`` (R3).

Named helpers for wait/skip, sampler flush, auth-gate bypass, post-cycle
recorder, and optimize-trigger mirror. Core wait/flush/superset logic stays in
``cycle`` / ``feed`` / ``superset`` — this module only wires them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShadowCyclePrep:
    """Result of :func:`prepare_shadow_cycle`."""

    trigger: str
    skipped: bool
    reason: str | None = None


def maybe_flush_after_sampler() -> None:
    """Prod-only sampler flush; never raises to the wait loop."""
    try:
        from runtime_store.shadow.feed import flush_after_sampler
        from runtime_store.shadow.mode import is_shadow_mode

        if not is_shadow_mode():
            flush_after_sampler()
    except Exception:  # noqa: BLE001 — never break wait loop
        logger.exception("shadow feed sampler flush failed")


def maybe_clear_auth_gate() -> bool:
    """If Shadow and auth recovery is needed, clear the gate and return True.

    Prod returns False so ``main`` keeps its live credential probe loop.
    """
    from runtime_store.shadow.mode import is_shadow_mode

    if not is_shadow_mode():
        return False
    from runtime_store.loxone_auth_error import clear_loxone_auth_error

    clear_loxone_auth_error()
    return True


def prepare_shadow_cycle(next_trigger: str, *, optimize_trigger: str) -> ShadowCyclePrep:
    """Shadow: consume optimize trigger + wait for Prod cycle.

    Non-Shadow: return *next_trigger* unchanged with ``skipped=False``.
    """
    from runtime_store.shadow.cycle import consume_optimize_trigger, wait_for_prod_cycle
    from runtime_store.shadow.mode import is_shadow_mode

    if not is_shadow_mode():
        return ShadowCyclePrep(trigger=next_trigger, skipped=False)

    trigger = next_trigger
    if consume_optimize_trigger():
        trigger = optimize_trigger
    cycle_info = wait_for_prod_cycle()
    if cycle_info.get("skipped"):
        return ShadowCyclePrep(
            trigger=trigger,
            skipped=True,
            reason=str(cycle_info.get("reason") or "unknown"),
        )
    return ShadowCyclePrep(trigger=trigger, skipped=False)


def after_prod_cycle() -> None:
    """Prod-only superset + feed flush after a successful cycle; soft-fail."""
    try:
        from runtime_store.shadow.feed import flush_after_cycle
        from runtime_store.shadow.mode import is_shadow_mode
        from runtime_store.shadow.superset import run_after_cycle as run_superset_after_cycle

        if not is_shadow_mode():
            run_superset_after_cycle()
            flush_after_cycle()
    except Exception:  # noqa: BLE001 — recorder must never break Prod
        logger.exception("shadow feed post-cycle failed")


def resolve_next_trigger(
    early: str | None,
    next_trigger: str,
    *,
    optimize_trigger: str,
) -> str:
    """Merge local early wake with Shadow feed optimize-trigger mirror."""
    if early == optimize_trigger:
        return optimize_trigger
    from runtime_store.shadow.cycle import consume_optimize_trigger
    from runtime_store.shadow.mode import is_shadow_mode

    if is_shadow_mode() and consume_optimize_trigger():
        return optimize_trigger
    return next_trigger
