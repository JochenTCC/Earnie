"""Throttle repeating setup-gate wait messages in the main daemon loop."""
from __future__ import annotations

import logging

logger = logging.getLogger("main")


def log_setup_gate_wait(
    state: dict,
    gate: str,
    message: str,
    *args,
    level: int = logging.WARNING,
    log: logging.Logger | None = None,
) -> None:
    """Log a setup-gate wait once at ``level``; repeat the same gate at DEBUG."""
    active = log if log is not None else logger
    if state.get("gate") != gate:
        state["gate"] = gate
        active.log(level, message, *args)
    else:
        active.debug(message, *args)
