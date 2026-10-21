"""Hub readiness for EHAL backends (Loxone / HA / OpenEMS)."""
from __future__ import annotations

import json
from typing import Any

from runtime_store.dotenv_io import loxone_credentials_configured
from runtime_store.persist_paths import resolve_config_json_path

BACKEND_LOXONE = "loxone"
BACKEND_HA = "ha"
BACKEND_OPENEMS = "openems"

# Historical constants (Binding P5e: transport key removed; HA is push-only).
HA_TRANSPORT_PULL = "pull"
HA_TRANSPORT_PUSH = "push"
HA_TRANSPORT_WEG_B_ALIAS = "weg_b"

HA_TRANSPORT_REMOVED_HINT = (
    "ehal.ha.transport is no longer supported (HA is push-only). "
    "Run config migration: Echtzeit-Umgebung → Migration, or "
    "python -m scripts.migrate_config"
)

_BACKEND_LABELS = {
    BACKEND_LOXONE: "Loxone",
    BACKEND_HA: "Home Assistant",
    BACKEND_OPENEMS: "OpenEMS",
}

_DEFAULT_ADAPTER_ID = {
    BACKEND_LOXONE: "loxone-home",
    BACKEND_HA: "earnie-hems",
    BACKEND_OPENEMS: "openems-lab",
}
_KNOWN_DEFAULT_ADAPTER_IDS = frozenset(_DEFAULT_ADAPTER_ID.values())


def backend_label(backend: str) -> str:
    return _BACKEND_LABELS.get(backend, backend)


def reject_leftover_ha_transport(ha_block: object) -> None:
    """Fail loud when ``ehal.ha.transport`` is still present after Binding P5e."""
    if isinstance(ha_block, dict) and "transport" in ha_block:
        raise ValueError(HA_TRANSPORT_REMOVED_HINT)


def normalize_ha_transport(raw: object) -> str:
    """Deprecated shim: HA is push-only (Binding P5e).

    Always returns ``push``. Call ``reject_leftover_ha_transport`` on the
    ``ehal.ha`` block first so a leftover ``transport`` key fails loud.
    Passing a non-empty raw value also fails (do not keep reading the key).
    """
    value = str(raw or "").strip().lower()
    if value == "":
        return HA_TRANSPORT_PUSH
    raise ValueError(HA_TRANSPORT_REMOVED_HINT)


def normalize_backend(raw: object) -> str:
    """``ehal.backend``: empty/``loxone``/``none`` → Loxone; ``ha`` / ``openems`` as-is.

    Unknown values raise; they must not silently become Loxone.
    """
    value = str(raw or "").strip().lower()
    if value in ("", "loxone", "none"):
        return BACKEND_LOXONE
    if value in (BACKEND_HA, BACKEND_OPENEMS):
        return value
    allowed = f"{BACKEND_HA!r}, {BACKEND_OPENEMS!r}, {BACKEND_LOXONE!r}, or 'none'"
    raise ValueError(f"ehal.backend must be {allowed}, got {raw!r}")


def default_adapter_id(backend: str) -> str:
    """Canonical default ``adapter_id`` for the given hub backend."""
    return _DEFAULT_ADAPTER_ID[normalize_backend(backend)]


def resolve_adapter_id(stored: object, backend: str) -> str:
    """Prefer a custom stored id; replace empty / foreign hub defaults."""
    wanted = default_adapter_id(backend)
    text = str(stored or "").strip()
    if not text or (text in _KNOWN_DEFAULT_ADAPTER_IDS and text != wanted):
        return wanted
    return text


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
    """Home Assistant needs no connection settings in Earnie (push-only, HA calls Earnie)."""
    del ehal
    return True


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
