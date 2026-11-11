"""Anonymous session counter of the Streamlit Community Cloud demo.

With ``EARNIE_CLOUD_DEMO=1`` every new browser session sends one POST
``{"v": 1}`` to ``earnie-server`` (``/demo-session``). The request comes from the
Streamlit server process, not from the visitor's browser: no install ID, no
configuration, no visitor IP. No consent dialog (maintainer decision 2026-11-09:
the count is anonymous); the demo's welcome note says so. ``EARNIE_USAGE_PING=off``
stops it like the install ping. Contract: ``docs/workflow/usage-ping.md``.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from runtime_store.cloud_demo import is_cloud_demo
from runtime_store.server_endpoints import PATH_DEMO_SESSION, post_json, resolve_endpoint
from runtime_store.usage_ping import is_kill_switch_off

logger = logging.getLogger(__name__)

PAYLOAD = b'{"v":1}'
TIMEOUT_SEC = 5.0

Transport = Callable[[str, bytes, float], int]


def _default_transport(url: str, body: bytes, timeout: float) -> int:
    return post_json(url, body, timeout, log_name="cloud_demo_session")


def send_demo_session(
    *, transport: Transport | None = None, endpoint_url: str | None = None
) -> bool:
    """POST one demo session count. Returns True on HTTP 2xx; no-op outside the demo."""
    if not is_cloud_demo() or is_kill_switch_off():
        return False
    url = resolve_endpoint(PATH_DEMO_SESSION, endpoint_url)
    send = transport if transport is not None else _default_transport
    status = int(send(url, PAYLOAD, TIMEOUT_SEC))
    if 200 <= status < 300:
        return True
    logger.warning("cloud_demo_session: send failed with status %s", status)
    return False


def _run() -> None:
    try:
        send_demo_session()
    except Exception as exc:  # noqa: BLE001 — a failed count must never reach the UI
        logger.warning("cloud_demo_session: send failed: %s", exc)


def spawn_demo_session_ping() -> threading.Thread | None:
    """Send in a daemon thread so the first page render does not wait for the server."""
    if not is_cloud_demo() or is_kill_switch_off():
        return None
    thread = threading.Thread(target=_run, name="cloud-demo-session", daemon=True)
    thread.start()
    return thread
