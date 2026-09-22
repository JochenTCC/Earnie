"""Home Assistant add-on Options → config.json (minimal 0.2 mapping).

On add-on start:
- Fresh ``config.json`` (just bootstrapped from minimal) → seed ``ehal.backend=ha``
- Every start → merge ``streamlit_port`` / ``ehal_loxone_http_port`` from
  ``/data/options.json`` into the matching config keys

Non-add-on installs are a no-op. Existing user configs are never force-switched
away from a chosen backend.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from runtime_store.install_context import detect_install_context
from runtime_store.persist_paths import resolve_config_json_path

logger = logging.getLogger(__name__)

DEFAULT_OPTIONS_PATH = "/data/options.json"
_HA_BACKEND = "ha"
_HA_ADAPTER_ID = "earnie-hems"


def options_path() -> str:
    return os.environ.get("EARNIE_ADDON_OPTIONS_PATH", DEFAULT_OPTIONS_PATH).strip() or (
        DEFAULT_OPTIONS_PATH
    )


def apply_addon_options(*, config_just_created: bool) -> bool:
    """Apply HA-add-on options to ``config.json``. Returns True if file changed."""
    if detect_install_context() != "homeassistant_addon":
        return False
    config_path = resolve_config_json_path()
    if not os.path.isfile(config_path):
        return False
    try:
        with open(config_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("addon_options: cannot read %s: %s", config_path, exc)
        return False
    if not isinstance(payload, dict):
        logger.warning("addon_options: %s root is not an object", config_path)
        return False

    changed = False
    if config_just_created:
        changed = _seed_ha_backend(payload) or changed
    options = _load_options(options_path())
    if options is not None:
        changed = _merge_port_options(payload, options) or changed

    if not changed:
        return False
    try:
        _write_config(config_path, payload)
    except OSError as exc:
        logger.warning("addon_options: cannot write %s: %s", config_path, exc)
        return False
    logger.info("addon_options: updated %s", config_path)
    return True


def _seed_ha_backend(payload: dict[str, Any]) -> bool:
    ehal = payload.setdefault("ehal", {})
    if not isinstance(ehal, dict):
        payload["ehal"] = ehal = {}
    before = (ehal.get("backend"), ehal.get("adapter_id"))
    ehal["backend"] = _HA_BACKEND
    ehal["adapter_id"] = _HA_ADAPTER_ID
    ha = ehal.setdefault("ha", {})
    if not isinstance(ha, dict):
        ehal["ha"] = ha = {}
    # Leave URL/token empty so runtime resolves Supervisor proxy.
    ha.setdefault("base_url", "")
    ha.setdefault("token", "")
    ha.setdefault("entities", ha.get("entities") if isinstance(ha.get("entities"), dict) else {})
    after = (ehal.get("backend"), ehal.get("adapter_id"))
    if before != after:
        logger.info("addon_options: seeded ehal.backend=%s for fresh add-on config", _HA_BACKEND)
        return True
    return False


def _merge_port_options(payload: dict[str, Any], options: dict[str, Any]) -> bool:
    changed = False
    streamlit_port = _as_port(options.get("streamlit_port"))
    if streamlit_port is not None:
        ui = payload.setdefault("ui", {})
        if not isinstance(ui, dict):
            payload["ui"] = ui = {}
        if ui.get("streamlit_port") != streamlit_port:
            ui["streamlit_port"] = streamlit_port
            changed = True
    loxone_http_port = _as_port(options.get("ehal_loxone_http_port"))
    if loxone_http_port is not None:
        system = payload.setdefault("system", {})
        if not isinstance(system, dict):
            payload["system"] = system = {}
        if system.get("ehal_loxone_http_port") != loxone_http_port:
            system["ehal_loxone_http_port"] = loxone_http_port
            changed = True
    return changed


def _load_options(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("addon_options: cannot read options %s: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        logger.warning("addon_options: options %s root is not an object", path)
        return None
    return raw


def _as_port(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if not 1024 <= port <= 65535:
        return None
    return port


def _write_config(path: str, payload: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
