"""LAN discovery for smarthome backends (Loxone / Home Assistant / OpenEMS).

Suggestions only — nothing here writes config or connects to a backend; callers
(the Smarthome-Backend UI page) must get explicit user confirmation before
persisting a result. See ``backlog/SB-Identification-Draft.md`` for the design
and ``docs/spec/smarthome-backend-page.md`` for how this module is used.

Passive methods (mDNS for Home Assistant, SSDP/UPnP for Loxone) are verified
against real hardware (Home Assistant 2026.8, Loxone Miniserver-Gen2). The
active OpenEMS port scan is unverified against a real OpenEMS Edge — its Felix
console signature check is best-effort corroboration; both ports open already
counts as a hit per the design draft.

The proprietary Loxone UDP broadcast discovery (port 7070, used internally by
Loxone Config) is intentionally NOT implemented: its wire format could not be
reverse-engineered against a real Miniserver (no response to several plausible
payloads), while SSDP was confirmed working and covers the same passive case.
"""
from __future__ import annotations

import http.client
import logging
import socket
from dataclasses import dataclass, field
from typing import Literal, Sequence

logger = logging.getLogger(__name__)

BackendKind = Literal["loxone", "home_assistant", "openems"]
ScanMode = Literal["targeted", "full_passive", "full_active"]

_MDNS_HA_SERVICE_TYPE = "_home-assistant._tcp.local."
_SSDP_MULTICAST_ADDR = ("239.255.255.250", 1900)
_OPENEMS_PORTS: tuple[int, ...] = (8080, 8085)
_OPENEMS_FELIX_PATH = "/system/console"


@dataclass(frozen=True)
class DiscoveredBackend:
    """One discovery hit. A suggestion — never auto-connected."""

    kind: BackendKind
    host: str
    method: Literal["mdns", "ssdp", "port_scan"]
    port: int | None = None
    name: str | None = None
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Home Assistant — passive mDNS
# --------------------------------------------------------------------------


def _ha_service_info_to_backend(info) -> DiscoveredBackend | None:
    """Pure mapping from a zeroconf ``ServiceInfo`` (duck-typed) to a hit."""
    addresses = list(getattr(info, "addresses", None) or [])
    if not addresses:
        return None
    host = socket.inet_ntoa(addresses[0])
    raw_props = getattr(info, "properties", None) or {}
    props: dict[str, str] = {}
    for key, value in raw_props.items():
        key_str = key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key)
        if value is None:
            continue
        value_str = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
        props[key_str] = value_str
    name = props.get("location_name") or str(getattr(info, "name", "") or "").split(".")[0] or None
    return DiscoveredBackend(
        kind="home_assistant",
        host=host,
        method="mdns",
        port=getattr(info, "port", None),
        name=name,
        extra={
            "base_url": props.get("base_url"),
            "internal_url": props.get("internal_url"),
            "uuid": props.get("uuid"),
            "version": props.get("version"),
        },
    )


def discover_home_assistant(*, timeout_sec: float = 4.0) -> list[DiscoveredBackend]:
    """mDNS browse for ``_home-assistant._tcp.local.``."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError as exc:
        logger.warning(
            "Home Assistant mDNS discovery unavailable (missing optional dependency zeroconf): %s",
            exc,
        )
        return []

    found: list[DiscoveredBackend] = []

    class _Listener:
        def add_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
            info = zc.get_service_info(service_type, name)
            if info is None:
                return
            backend = _ha_service_info_to_backend(info)
            if backend is not None:
                found.append(backend)

        def remove_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
            return None

        def update_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
            return None

    zc = None
    try:
        zc = Zeroconf()
        ServiceBrowser(zc, _MDNS_HA_SERVICE_TYPE, _Listener())
        import time

        time.sleep(timeout_sec)
    except OSError as exc:
        logger.warning("Home Assistant mDNS discovery failed: %s", exc)
    finally:
        if zc is not None:
            zc.close()

    by_host = {backend.host: backend for backend in found}
    return list(by_host.values())


# --------------------------------------------------------------------------
# Loxone — passive SSDP/UPnP
# --------------------------------------------------------------------------

_SSDP_REQUEST = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: ssdp:all\r\n"
    "\r\n"
).encode("utf-8")


def _parse_ssdp_headers(raw: bytes) -> dict[str, str]:
    """HTTP/1.1-style SSDP response → lower-cased header dict (status line dropped)."""
    headers: dict[str, str] = {}
    for line in raw.decode("utf-8", "replace").split("\r\n")[1:]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    return headers


def _ssdp_response_to_backend(host: str, headers: dict[str, str]) -> DiscoveredBackend | None:
    """Pure classification: is this SSDP response a Loxone Miniserver?"""
    server = headers.get("server", "")
    if "loxone" not in server.lower():
        return None
    location = headers.get("location", "")
    port = 80
    if location:
        try:
            port = int(location.split("://", 1)[-1].split("/", 1)[0].split(":")[1])
        except (IndexError, ValueError):
            port = 80
    name = server.replace("UPnP/1.0", "").strip() or None
    return DiscoveredBackend(
        kind="loxone",
        host=host,
        method="ssdp",
        port=port,
        name=name,
        extra={"location": location or None, "server": server},
    )


def discover_loxone(*, timeout_sec: float = 3.0) -> list[DiscoveredBackend]:
    """SSDP M-SEARCH broadcast; Miniservers answer with a ``Loxone`` SERVER header."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_sec)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    found: dict[str, DiscoveredBackend] = {}
    try:
        sock.sendto(_SSDP_REQUEST, _SSDP_MULTICAST_ADDR)
        import time

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            except OSError:
                break
            backend = _ssdp_response_to_backend(addr[0], _parse_ssdp_headers(data))
            if backend is not None:
                found[backend.host] = backend
    except OSError as exc:
        logger.warning("Loxone SSDP discovery failed: %s", exc)
    finally:
        sock.close()
    return list(found.values())


# --------------------------------------------------------------------------
# OpenEMS — active port scan (opt-in only)
# --------------------------------------------------------------------------


def _looks_like_felix_console(headers: dict[str, str], body: str) -> bool:
    """Best-effort corroboration only — not verified against a real OpenEMS Edge."""
    www_auth = headers.get("www-authenticate", "")
    if "felix" in www_auth.lower():
        return True
    if "felix" in body.lower():
        return True
    return False


def _probe_felix_console(host: str, port: int, *, timeout_sec: float) -> bool:
    conn = http.client.HTTPConnection(host, port, timeout=timeout_sec)
    try:
        conn.request("GET", _OPENEMS_FELIX_PATH)
        response = conn.getresponse()
        body = response.read(4096).decode("utf-8", "replace")
        headers = {k.lower(): v for k, v in response.getheaders()}
        return _looks_like_felix_console(headers, body)
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def _tcp_port_open(host: str, port: int, *, timeout_sec: float) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_sec)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def local_ipv4_hosts_for_scan(*, subnet_size: int = 24) -> list[str]:
    """Candidate hosts on the local /24 (home-LAN assumption, same as elsewhere in Earnie).

    Determines the local IPv4 address without sending traffic (UDP "connect" to a
    public IP only resolves routing, per the standard socket trick), then assumes a
    /24 subnet. Excludes the network address, broadcast address and own IP.
    """
    if subnet_size != 24:
        raise ValueError("only /24 is supported for now")
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        local_ip = probe.getsockname()[0]
    except OSError:
        return []
    finally:
        probe.close()
    prefix = ".".join(local_ip.split(".")[:3])
    return [f"{prefix}.{i}" for i in range(1, 255) if f"{prefix}.{i}" != local_ip]


def discover_openems(
    hosts: Sequence[str] | None = None,
    *,
    timeout_sec: float = 0.5,
) -> list[DiscoveredBackend]:
    """Active TCP scan for ports 8080 (Felix)/8085 (UI websocket). Opt-in only.

    ``hosts`` defaults to :func:`local_ipv4_hosts_for_scan` — pass an explicit
    list to scan a narrower range (e.g. after a slow full-subnet pass timed out).
    """
    candidates = list(hosts) if hosts is not None else local_ipv4_hosts_for_scan()
    found: list[DiscoveredBackend] = []
    for host in candidates:
        open_ports = [
            port
            for port in _OPENEMS_PORTS
            if _tcp_port_open(host, port, timeout_sec=timeout_sec)
        ]
        if not open_ports:
            continue
        felix_confirmed = 8080 in open_ports and _probe_felix_console(
            host, 8080, timeout_sec=timeout_sec
        )
        found.append(
            DiscoveredBackend(
                kind="openems",
                host=host,
                method="port_scan",
                port=8080 if 8080 in open_ports else open_ports[0],
                name=None,
                extra={"open_ports": open_ports, "felix_console_confirmed": felix_confirmed},
            )
        )
    return found


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def scan_for_backends(
    mode: ScanMode = "full_passive",
    *,
    only_kinds: Sequence[BackendKind] | None = None,
    timeout_sec: float | None = None,
) -> list[DiscoveredBackend]:
    """Run the discovery methods implied by ``mode``, optionally filtered by kind.

    - ``targeted``: only the kind(s) in ``only_kinds`` (from install-context
      detection). Falls back to ``full_passive`` behaviour if ``only_kinds`` is
      empty/omitted — there is nothing to target without it.
    - ``full_passive``: mDNS (Home Assistant) + SSDP (Loxone). No network writes
      beyond standard discovery broadcasts.
    - ``full_active``: ``full_passive`` plus the OpenEMS port scan. Callers must
      only reach this mode after explicit user consent (firewall/IDS risk).
    """
    kinds = set(only_kinds) if only_kinds else None
    run_ha = kinds is None or "home_assistant" in kinds
    run_loxone = kinds is None or "loxone" in kinds
    run_openems = mode == "full_active" and (kinds is None or "openems" in kinds)

    results: list[DiscoveredBackend] = []
    if run_ha:
        kwargs = {"timeout_sec": timeout_sec} if timeout_sec is not None else {}
        results.extend(discover_home_assistant(**kwargs))
    if run_loxone:
        kwargs = {"timeout_sec": timeout_sec} if timeout_sec is not None else {}
        results.extend(discover_loxone(**kwargs))
    if run_openems:
        kwargs = {"timeout_sec": timeout_sec} if timeout_sec is not None else {}
        results.extend(discover_openems(**kwargs))
    return results
