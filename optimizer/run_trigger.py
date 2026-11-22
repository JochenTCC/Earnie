"""Optimize run trigger labels and wait-until-next-run helpers."""
from __future__ import annotations

import logging
import time
from typing import Callable

from integrations.ehal_request_http import wait_for_optimize_or_timeout

logger = logging.getLogger(__name__)

TRIGGER_QUARTER_HOUR = "quarter_hour"
TRIGGER_REQUEST_OPTIMIZE = "request_optimize"
# Reserve P1: an appliance of a filled virtual reserve started during the wait.
TRIGGER_RESERVE_RELEASE = "reserve_release"

# Same cadence as the power-interval sampler (``SAMPLE_INTERVAL_SEC``).
RESERVE_CHECK_INTERVAL_SEC = 30.0


def is_out_of_band_trigger(run_trigger: str) -> bool:
    return run_trigger != TRIGGER_QUARTER_HOUR


def wait_until_next_run(
    *,
    total_wait_sec: float,
    poll_interval_sec: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_poll: Callable[[], str | None] | None = None,
    clock_fn: Callable[[], float] = time.monotonic,
) -> str | None:
    """Wait until next quarter-hour, Earnie_Request_Optimize or an ``on_poll`` wake.

    Returns ``TRIGGER_REQUEST_OPTIMIZE`` if woken by the request, the label
    ``on_poll`` returned if it asked for a run, else ``None``.
    ``on_poll`` runs each wait chunk (e.g. power-interval sampler tick); its
    runtime counts towards ``total_wait_sec`` (monotonic deadline via ``clock_fn``).
    A non-empty string from ``on_poll`` ends the wait with that trigger label.
    """
    woken: list[str] = []

    def _poll() -> None:
        label = on_poll() if on_poll is not None else None
        if label:
            woken.append(str(label))

    if wait_for_optimize_or_timeout(
        total_wait_sec,
        poll_interval_sec=poll_interval_sec,
        sleep_fn=sleep_fn,
        on_poll=_poll if on_poll is not None else None,
        clock_fn=clock_fn,
        stop_fn=lambda: bool(woken),
    ):
        logger.info(
            "Earnie_Request_Optimize — Optimierung wird vorzeitig angestoßen."
        )
        return TRIGGER_REQUEST_OPTIMIZE
    if woken:
        return woken[0]
    return None


def reserve_release_poll(
    *,
    base_poll: Callable[[], None],
    check_release: Callable[[], bool],
    wake_until: float,
    clock_fn: Callable[[], float] = time.monotonic,
    interval_sec: float = RESERVE_CHECK_INTERVAL_SEC,
) -> Callable[[], str | None]:
    """``on_poll`` for the daemon wait that also releases virtual reserves (Reserve P1).

    Runs ``base_poll`` (heartbeat, sampler) on every chunk. Every
    ``interval_sec`` (first chunk included) and only before ``wake_until``
    (monotonic: next regular start minus the expected run time) it calls
    ``check_release``; ``True`` means a reserve was latched and the wait ends
    with ``TRIGGER_RESERVE_RELEASE``. After ``wake_until`` the next regular
    run comes first and picks the trigger up itself.
    """
    last_check: list[float] = []

    def poll() -> str | None:
        base_poll()
        now = clock_fn()
        if now >= wake_until:
            return None
        if last_check and now - last_check[0] < interval_sec:
            return None
        last_check[:] = [now]
        if check_release():
            return TRIGGER_RESERVE_RELEASE
        return None

    return poll
