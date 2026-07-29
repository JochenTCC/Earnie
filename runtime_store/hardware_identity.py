"""Best-effort hardware identity for registry fingerprint (2.4.i spike)."""
from __future__ import annotations

import hashlib
import os
import sys
from typing import Mapping

from runtime_store.env_vars import read_env

# Canonical part keys (sorted order used in fingerprint).
PART_KEYS = ("ha", "host", "loxone", "openems")

DISPLAY_FINGERPRINT_CHARS = 16


def _read_linux_machine_id() -> str:
    path = "/etc/machine-id"
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _read_windows_machine_guid() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
    except OSError:
        return ""
    try:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
    except OSError:
        return ""
    finally:
        winreg.CloseKey(key)
    return str(value).strip() if value else ""


def read_host_machine_id() -> str:
    """Return host machine id, or empty string on failure."""
    if sys.platform == "win32":
        return _read_windows_machine_guid()
    return _read_linux_machine_id()


def collect_hardware_identity(
    *,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """
    Collect identity parts (empty strings omitted from fingerprint input).

    Env (via ``read_env``): ``LOXONE_SERIAL``, ``HA_INSTANCE_ID``, ``OPENEMS_EDGE_ID``.
    Host is always probed unless overridden.
    """
    parts: dict[str, str] = {
        "host": read_host_machine_id(),
        "loxone": read_env("LOXONE_SERIAL"),
        "ha": read_env("HA_INSTANCE_ID"),
        "openems": read_env("OPENEMS_EDGE_ID"),
    }
    if overrides:
        for key, value in overrides.items():
            if key in PART_KEYS:
                parts[key] = str(value).strip() if value is not None else ""
    return {key: parts.get(key, "") for key in PART_KEYS}


def fingerprint_payload(parts: Mapping[str, str]) -> str:
    """Canonical UTF-8 payload for hashing (sorted non-empty key=value lines)."""
    lines: list[str] = []
    for key in sorted(PART_KEYS):
        value = str(parts.get(key, "") or "").strip()
        if value:
            lines.append(f"{key}={value}")
    return "\n".join(lines)


def compute_hardware_fingerprint(parts: Mapping[str, str]) -> str:
    """SHA-256 hex of canonical payload; empty parts → hash of empty string."""
    payload = fingerprint_payload(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def collect_and_fingerprint(
    *,
    overrides: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], str]:
    """Return (parts, full fingerprint)."""
    parts = collect_hardware_identity(overrides=overrides)
    return parts, compute_hardware_fingerprint(parts)


def display_fingerprint(fingerprint: str) -> str:
    """Short display form (first N hex chars); empty input stays empty."""
    text = (fingerprint or "").strip()
    if not text:
        return ""
    return text[:DISPLAY_FINGERPRINT_CHARS]
