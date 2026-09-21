"""Home Assistant Core access via the Supervisor proxy (HA add-on only).

When Earnie runs as a Supervisor add-on with ``homeassistant_api: true``, the
Supervisor injects ``SUPERVISOR_TOKEN`` and exposes Core at
``http://supervisor/core``. That path does not need mDNS or a manually created
long-lived access token.

Do **not** persist ``SUPERVISOR_TOKEN`` into ``config.json`` — it is ephemeral
and Supervisor-owned.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from runtime_store.install_context import detect_install_context

if TYPE_CHECKING:
    from integrations.integration_scanner import DiscoveredBackend

logger = logging.getLogger(__name__)

SUPERVISOR_CORE_BASE_URL = "http://supervisor/core"
_SUPERVISOR_CORE_API = f"{SUPERVISOR_CORE_BASE_URL}/api/"
_SUPERVISOR_ADDON_SELF_INFO = "http://supervisor/addons/self/info"
_PROBE_TIMEOUT_SEC = 3.0


def supervisor_token() -> str:
    return str(os.environ.get("SUPERVISOR_TOKEN") or "").strip()


def is_homeassistant_addon_context() -> bool:
    return detect_install_context() == "homeassistant_addon"


def supervisor_proxy_available() -> bool:
    return is_homeassistant_addon_context() and bool(supervisor_token())


def fetch_ingress_entry(*, timeout_sec: float = _PROBE_TIMEOUT_SEC) -> str:
    """Return Supervisor ``ingress_entry`` (e.g. ``/api/hassio_ingress/<token>``).

    Uses ``GET /addons/self/info`` (available without ``hassio_api: true``).
    Empty when not an add-on, token missing, or Ingress not configured.
    """
    token = supervisor_token()
    if not token or not is_homeassistant_addon_context():
        return ""
    request = urllib.request.Request(
        _SUPERVISOR_ADDON_SELF_INFO,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.info("Supervisor add-on self/info failed: %s", exc)
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.info("Supervisor add-on self/info JSON invalid: %s", exc)
        return ""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return ""
    entry = str(data.get("ingress_entry") or "").strip()
    return entry


def streamlit_base_url_path(*, timeout_sec: float = _PROBE_TIMEOUT_SEC) -> str:
    """Streamlit ``--server.baseUrlPath`` value (no leading slash), or empty.

    Prefer ``EARNIE_STREAMLIT_BASE_URL_PATH`` (set by the add-on ``run.sh`` when
    nginx Ingress proxy is active). Falls back to Supervisor ``ingress_entry``.
    """
    override = str(os.environ.get("EARNIE_STREAMLIT_BASE_URL_PATH") or "").strip()
    if override:
        return override.lstrip("/")
    entry = fetch_ingress_entry(timeout_sec=timeout_sec)
    return entry.lstrip("/") if entry else ""


def resolve_ha_base_url(configured: str) -> str:
    """Config URL, or Supervisor Core proxy when running as the HA add-on."""
    value = str(configured or "").strip()
    if value:
        return value
    if is_homeassistant_addon_context():
        return SUPERVISOR_CORE_BASE_URL
    return ""


def resolve_ha_token(configured: str) -> str:
    """Config token, or ``SUPERVISOR_TOKEN`` when present (add-on)."""
    value = str(configured or "").strip()
    if value:
        return value
    return supervisor_token()


def probe_supervisor_core(*, timeout_sec: float = _PROBE_TIMEOUT_SEC) -> bool:
    """True when ``GET /api/`` on the Supervisor Core proxy succeeds."""
    token = supervisor_token()
    if not token:
        return False
    request = urllib.request.Request(
        _SUPERVISOR_CORE_API,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            return 200 <= int(response.status) < 300
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.info("Supervisor Core API probe failed: %s", exc)
        return False


def discover_home_assistant_via_supervisor(
    *,
    timeout_sec: float = _PROBE_TIMEOUT_SEC,
) -> list[DiscoveredBackend]:
    """Return a single Supervisor Core hit when the proxy responds."""
    from integrations.integration_scanner import DiscoveredBackend

    if not supervisor_proxy_available():
        return []
    if not probe_supervisor_core(timeout_sec=timeout_sec):
        return []
    return [
        DiscoveredBackend(
            kind="home_assistant",
            host="supervisor",
            method="supervisor",
            port=None,
            name="Home Assistant (Supervisor)",
            extra={"base_url": SUPERVISOR_CORE_BASE_URL},
        )
    ]
