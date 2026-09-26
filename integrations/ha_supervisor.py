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
import time
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
_SUPERVISOR_NETWORK_INFO = "http://supervisor/network/info"
_PROBE_TIMEOUT_SEC = 3.0
# Host interfaces whose names imply Docker / hassio, not the LAN.
_SKIP_INTERFACE_NAME_FRAGMENTS = ("hassio", "docker", "veth", "br-")


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


def wait_for_supervisor_core(
    *,
    max_wait_sec: float = 60.0,
    interval_sec: float = 2.0,
    probe_timeout_sec: float = _PROBE_TIMEOUT_SEC,
) -> bool:
    """Poll Core API until ready or ``max_wait_sec`` elapses (add-on H7).

    Returns True when a probe succeeds. On timeout logs a warning and returns
    False so the daemon/UI can continue (later EHAL cycles may still succeed).
    Returns True immediately when not in add-on context. Returns False when
    add-on context lacks ``SUPERVISOR_TOKEN``.
    """
    if not is_homeassistant_addon_context():
        return True
    if not supervisor_token():
        logger.warning(
            "HA add-on context without SUPERVISOR_TOKEN; skipping Core wait"
        )
        return False
    deadline = time.monotonic() + max(0.0, float(max_wait_sec))
    interval = max(0.1, float(interval_sec))
    attempt = 0
    while True:
        attempt += 1
        if probe_supervisor_core(timeout_sec=probe_timeout_sec):
            if attempt > 1:
                logger.info(
                    "Supervisor Core API ready after %s probe(s)", attempt
                )
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning(
                "Supervisor Core API not ready after %.0fs (%s probes); continuing",
                max_wait_sec,
                attempt,
            )
            return False
        time.sleep(min(interval, remaining))


def _ipv4_from_address_entry(entry: object) -> str | None:
    """Parse ``192.168.1.10/24`` or bare ``192.168.1.10`` → host IPv4 string."""
    raw = str(entry or "").strip()
    if not raw:
        return None
    host = raw.split("/", 1)[0].strip()
    parts = host.split(".")
    if len(parts) != 4:
        return None
    try:
        if not all(0 <= int(p) <= 255 for p in parts):
            return None
    except ValueError:
        return None
    return host


def _interface_should_skip(iface: dict) -> bool:
    name = str(iface.get("interface") or iface.get("name") or "").lower()
    return any(frag in name for frag in _SKIP_INTERFACE_NAME_FRAGMENTS)


def _ipv4_from_interface(iface: dict) -> str | None:
    """Extract first usable IPv4 from a Supervisor interface dict."""
    from integrations.integration_scanner import is_docker_bridge_ipv4

    ipv4 = iface.get("ipv4")
    if isinstance(ipv4, dict):
        addresses = ipv4.get("address") or []
        if isinstance(addresses, str):
            addresses = [addresses]
        for entry in addresses:
            host = _ipv4_from_address_entry(entry)
            if host and not is_docker_bridge_ipv4(host):
                return host
    # Older docs used a single ``ip_address`` field.
    host = _ipv4_from_address_entry(iface.get("ip_address"))
    if host and not is_docker_bridge_ipv4(host):
        return host
    return None


def _pick_host_lan_ipv4(interfaces: list) -> str | None:
    """Prefer primary connected interface; skip Docker-named / Docker-range IPs."""
    ranked: list[tuple[int, str]] = []
    for item in interfaces:
        if not isinstance(item, dict) or _interface_should_skip(item):
            continue
        host = _ipv4_from_interface(item)
        if not host:
            continue
        primary = 0 if item.get("primary") else 1
        connected = 0 if item.get("connected", True) else 1
        ranked.append((primary + connected, host))
    if not ranked:
        return None
    ranked.sort(key=lambda row: row[0])
    return ranked[0][1]


def supervisor_host_lan_ipv4(*, timeout_sec: float = _PROBE_TIMEOUT_SEC) -> str | None:
    """Host LAN IPv4 from Supervisor ``GET /network/info`` (HA add-on, ``hassio_api``).

    Returns ``None`` when not an add-on, token missing, request fails, or no
    suitable non-Docker host address is found.
    """
    token = supervisor_token()
    if not token or not is_homeassistant_addon_context():
        return None
    request = urllib.request.Request(
        _SUPERVISOR_NETWORK_INFO,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.info("Supervisor network/info failed: %s", exc)
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.info("Supervisor network/info JSON invalid: %s", exc)
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    interfaces = data.get("interfaces")
    if isinstance(interfaces, dict):
        # Docs example keyed by name; live API returns a list.
        iface_list = [
            {**value, "interface": key}
            if isinstance(value, dict)
            else value
            for key, value in interfaces.items()
        ]
    elif isinstance(interfaces, list):
        iface_list = interfaces
    else:
        return None
    return _pick_host_lan_ipv4(iface_list)


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
