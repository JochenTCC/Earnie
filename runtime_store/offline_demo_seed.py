"""Seed live-scenario entity refs when EARNIE_OFFLINE and refs are empty."""
from __future__ import annotations

import logging
import os
from typing import Any

from runtime_store.env_vars import is_explicit_offline
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
)
from settings.json_io import read_json_dict, write_json_dict

logger = logging.getLogger(__name__)

_REF_KEYS = (
    "battery_id",
    "import_tariff_id",
    "export_tariff_id",
    "house_profile_id",
)


def _first_id(items: list[Any]) -> str:
    for item in items:
        if isinstance(item, dict):
            value = str(item.get("id", "") or "").strip()
            if value:
                return value
    return ""


def _prefer_id(items: list[Any], preferred: str) -> str:
    preferred = preferred.strip()
    if preferred:
        for item in items:
            if isinstance(item, dict) and str(item.get("id", "") or "").strip() == preferred:
                return preferred
    return _first_id(items)


def _first_fixed_export_id(exports: list[Any]) -> str:
    preferred = _prefer_id(exports, "fixed_37ct")
    if preferred:
        for item in exports:
            if not isinstance(item, dict):
                continue
            if str(item.get("id", "") or "").strip() != preferred:
                continue
            if item.get("type") == "fixed" and "k_push_cent" in item:
                return preferred
    for item in exports:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "fixed" and "k_push_cent" in item:
            value = str(item.get("id", "") or "").strip()
            if value:
                return value
    return _first_id(exports)


def _profile_ids(profiles_doc: dict) -> list[str]:
    profiles = profiles_doc.get("profiles", [])
    if isinstance(profiles, dict):
        return [str(key).strip() for key in profiles if str(key).strip()]
    if isinstance(profiles, list):
        return [
            str(item.get("id", "") or "").strip()
            for item in profiles
            if isinstance(item, dict) and str(item.get("id", "") or "").strip()
        ]
    return []


def _catalog_defaults() -> dict[str, Any]:
    components = read_json_dict(resolve_components_json_path())
    tariffs = read_json_dict(resolve_tariffs_json_path())
    profiles = read_json_dict(resolve_house_profiles_json_path())
    profile_ids = _profile_ids(profiles)
    house_profile_id = (
        "example_efh" if "example_efh" in profile_ids else (profile_ids[0] if profile_ids else "")
    )
    pv_id = _first_id(components.get("pv_systems", []) or [])
    return {
        "battery_id": _first_id(components.get("batteries", []) or []),
        "pv_system_ids": [pv_id] if pv_id else [],
        "import_tariff_id": _prefer_id(
            tariffs.get("import_tariffs", []) or [], "awattar_at"
        ),
        "export_tariff_id": _first_fixed_export_id(
            tariffs.get("export_tariffs", []) or []
        ),
        "house_profile_id": house_profile_id,
    }


def _settings_incomplete(settings: dict) -> bool:
    for key in _REF_KEYS:
        if not str(settings.get(key, "") or "").strip():
            return True
    return False


def live_scenario_refs_incomplete(
    *,
    config_path: str | None = None,
    scenarios_path: str | None = None,
) -> bool:
    """True when live scenario entity refs are missing (Cloud minimal bootstrap)."""
    config_path = config_path or resolve_config_json_path()
    scenarios_path = scenarios_path or resolve_backtesting_scenarios_json_path()
    try:
        raw_config = read_json_dict(config_path)
    except (OSError, ValueError):
        return True
    from house_config.scenario_resolution import (
        find_scenario_settings,
        get_live_scenario_id,
    )

    live_id = get_live_scenario_id(raw_config)
    try:
        settings = find_scenario_settings(scenarios_path, live_id)
    except (OSError, ValueError, KeyError):
        return True
    return _settings_incomplete(settings)


def _fill_empty_refs(settings: dict, defaults: dict[str, Any]) -> list[str]:
    filled: list[str] = []
    for key in _REF_KEYS:
        if str(settings.get(key, "") or "").strip():
            continue
        value = defaults.get(key, "")
        if not value:
            continue
        settings[key] = value
        filled.append(key)
    pv_ids = settings.get("pv_system_ids")
    has_pv = isinstance(pv_ids, list) and any(str(x).strip() for x in pv_ids)
    if not has_pv:
        default_pv = defaults.get("pv_system_ids") or []
        if default_pv:
            settings["pv_system_ids"] = list(default_pv)
            filled.append("pv_system_ids")
    return filled


def seed_offline_live_scenario() -> bool:
    """
    When EARNIE_OFFLINE=1, fill empty live-scenario entity IDs from catalogs.

    Never overwrites non-empty refs. Returns True if the scenarios file changed.
    """
    if not is_explicit_offline():
        return False
    config_path = resolve_config_json_path()
    scenarios_path = resolve_backtesting_scenarios_json_path()
    if not os.path.isfile(config_path) or not os.path.isfile(scenarios_path):
        return False
    raw_config = read_json_dict(config_path)
    from house_config.scenario_resolution import get_live_scenario_id

    live_id = get_live_scenario_id(raw_config)
    doc = read_json_dict(scenarios_path)
    scenarios = doc.get("scenarios")
    if not isinstance(scenarios, list):
        return False
    defaults = _catalog_defaults()
    changed = False
    for entry in scenarios:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id", "") or "").strip() != live_id:
            continue
        settings = entry.get("settings")
        if not isinstance(settings, dict):
            settings = {}
            entry["settings"] = settings
        filled = _fill_empty_refs(settings, defaults)
        if filled:
            changed = True
            logger.info(
                "offline demo seed: live scenario %r filled %s",
                live_id,
                ", ".join(filled),
            )
        break
    if not changed:
        return False
    write_json_dict(scenarios_path, doc)
    return True
