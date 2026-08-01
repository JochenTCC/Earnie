"""Optimize run trigger labels and wait-until-next-run helpers."""
from __future__ import annotations

import logging
import time
from typing import Callable

from integrations.loxone_request_http import wait_for_optimize_or_timeout

logger = logging.getLogger(__name__)

TRIGGER_QUARTER_HOUR = "quarter_hour"
TRIGGER_REQUEST_OPTIMIZE = "request_optimize"


def is_out_of_band_trigger(run_trigger: str) -> bool:
    return run_trigger != TRIGGER_QUARTER_HOUR


def wait_until_next_run(
    *,
    total_wait_sec: float,
    poll_interval_sec: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str | None:
    """Wait until next quarter-hour or Earnie_Request_Optimize wake.

    Returns ``TRIGGER_REQUEST_OPTIMIZE`` if woken early, else ``None``.
    """
    if wait_for_optimize_or_timeout(
        total_wait_sec,
        poll_interval_sec=poll_interval_sec,
        sleep_fn=sleep_fn,
    ):
        logger.info(
            "Earnie_Request_Optimize — Optimierung wird vorzeitig angestoßen."
        )
        return TRIGGER_REQUEST_OPTIMIZE
    return None
