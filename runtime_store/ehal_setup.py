"""Hub readiness for EHAL backends (Loxone / HA / OpenEMS)."""
from __future__ import annotations

import json
from typing import Any

from runtime_store.dotenv_io import loxone_credentials_configured
from runtime_store.persist_paths import resolve_config_json_path

BACKEND_LOXONE = "loxone"
BACKEND_HA = "ha"
BACKEND_OPENEMS = "openems"

_BACKEND_LABELS = {
    BACKEND_LOXONE: "Loxone",
    BACKEND_HA: "Home Assistant",
    BACKEND_OPENEMS: "OpenEMS",
}


def backend_label(backend: str) -> str:
    return _BACKEND_LABELS.get(backend, backend)


def normalize_backend(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if value in ("", "loxone", "none"):
        return BACKEND_LOXONE
    if value in (BACKEND_HA, BACKEND_OPENEMS):
        return value
    return BACKEND_LOXONE


def _read_config_json() -> dict[str, Any]:
    path = resolve_config_json_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def active_ehal_backend(raw_config: dict[str, Any] | None = None) -> str:
    """Return active hub: loxone | ha | openems."""
    data = raw_config if isinstance(raw_config, dict) else _read_config_json()
    ehal = data.get("ehal") if isinstance(data.get("ehal"), dict) else {}
    return normalize_backend(ehal.get("backend"))


def _ha_credentials_configured(ehal: dict[str, Any]) -> bool:
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    base_url = str(ha.get("base_url") or "").strip()
    token = str(ha.get("token") or "").strip()
    return bool(base_url and token)


def _openems_credentials_configured(ehal: dict[str, Any]) -> bool:
    openems = ehal.get("openems") if isinstance(ehal.get("openems"), dict) else {}
    return bool(str(openems.get("base_url") or "").strip())


def hub_credentials_configured(
    backend: str | None = None,
    *,
    raw_config: dict[str, Any] | None = None,
) -> bool:
    """True when the active (or given) hub has usable connection settings."""
    data = raw_config if isinstance(raw_config, dict) else _read_config_json()
    resolved = normalize_backend(backend) if backend is not None else active_ehal_backend(data)
    if resolved == BACKEND_LOXONE:
        return loxone_credentials_configured()
    ehal = data.get("ehal") if isinstance(data.get("ehal"), dict) else {}
    if resolved == BACKEND_HA:
        return _ha_credentials_configured(ehal)
    if resolved == BACKEND_OPENEMS:
        return _openems_credentials_configured(ehal)
    return False


def is_network_backend(backend: str | None = None) -> bool:
    resolved = normalize_backend(backend) if backend is not None else active_ehal_backend()
    return resolved in (BACKEND_HA, BACKEND_OPENEMS)
