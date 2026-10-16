"""Earnie-Points of the **live** plant for the usage ping (``docs/spec/earnie-points.md`` §4).

Resolves the live scenario (config.json ``live_scenario_id`` → backtesting_scenarios.json),
selects its PV systems / house batteries (powerstations are always part of the plant) and its
house profile, and calls the pure ``compute_earnie_points``. ``refresh_points`` keeps
``points`` / ``points_v`` / ``points_stamp`` in the usage-ping state.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from house_config.components_store import load_components_document
from house_config.earnie_points import POINTS_RULE_VERSION, compute_earnie_points
from house_config.entity_resolution import normalize_battery_ids, normalize_pv_system_ids
from house_config.powerstation import is_powerstation
from house_config.profiles_store import load_house_profiles_document
from house_config.scenario_resolution import find_scenario_settings, get_live_scenario_id
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
    resolve_house_profiles_json_path,
)
from settings.json_io import read_json_dict

logger = logging.getLogger(__name__)

_STAMP_SOURCES = {
    "config": resolve_config_json_path,
    "scenarios": resolve_backtesting_scenarios_json_path,
    "components": resolve_components_json_path,
    "profiles": resolve_house_profiles_json_path,
}


def _mtime_ns(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return -1


def config_stamp() -> dict[str, int]:
    """mtimes of every file the live points depend on (``-1`` when missing)."""
    return {name: _mtime_ns(resolver()) for name, resolver in _STAMP_SOURCES.items()}


def _select_by_ids(items: list, wanted: list[str], *, section: str) -> list[dict]:
    by_id = {str(item.get("id") or "").strip(): item for item in items if isinstance(item, dict)}
    missing = [item_id for item_id in wanted if item_id not in by_id]
    if missing:
        raise ValueError(
            f"Live-Szenario verweist auf unbekannte {section}: {', '.join(missing)}."
        )
    return [by_id[item_id] for item_id in wanted]


def _live_components(components: dict, settings: dict) -> dict:
    """Components of the live plant: selected PV + house batteries, all powerstations."""
    pv_systems = _select_by_ids(
        components.get("pv_systems", []),
        normalize_pv_system_ids(settings),
        section="pv_systems",
    )
    all_batteries = [b for b in components.get("batteries", []) if isinstance(b, dict)]
    house = _select_by_ids(
        [b for b in all_batteries if not is_powerstation(b)],
        normalize_battery_ids(settings),
        section="batteries",
    )
    powerstations = [b for b in all_batteries if is_powerstation(b)]
    return {"pv_systems": pv_systems, "batteries": house + powerstations}


def _live_profile(settings: dict) -> dict:
    profile_id = str(settings.get("house_profile_id") or "").strip()
    if not profile_id:
        raise ValueError("Live-Szenario hat kein house_profile_id.")
    doc = load_house_profiles_document(resolve_house_profiles_json_path())
    profile = (doc.get("profiles") or {}).get(profile_id)
    if not isinstance(profile, dict):
        raise ValueError(f"Live-Szenario verweist auf unbekanntes house_profile_id '{profile_id}'.")
    return profile


def compute_live_points() -> dict[str, int]:
    """Earnie-Points breakdown (``total`` + parts) of the plant the live daemon runs on."""
    live_id = get_live_scenario_id(read_json_dict(resolve_config_json_path()))
    settings = find_scenario_settings(resolve_backtesting_scenarios_json_path(), live_id)
    components = load_components_document(resolve_components_json_path())
    return compute_earnie_points(_live_components(components, settings), _live_profile(settings))


def _apply_points(state: dict[str, Any], breakdown: dict[str, int] | None) -> bool:
    """Write (or clear) points in ``state``; return True when the sent value changed."""
    old = (state.get("points"), state.get("points_v"))
    if breakdown is None:
        state.pop("points", None)
        state.pop("points_v", None)
    else:
        state["points"] = int(breakdown["total"])
        state["points_v"] = POINTS_RULE_VERSION
    return old != (state.get("points"), state.get("points_v"))


def refresh_points() -> bool:
    """Recompute live points when the config stamp changed; return True if the value changed.

    Consent must be ``on``. A calculation error logs a WARNING and removes ``points`` so a
    stale value is never sent (the ping then goes out as schema v1). The stamp is stored
    either way, so a broken config is evaluated once per change, not every cycle.
    """
    from runtime_store import usage_ping as up

    state = up.load_state()
    if str(state.get("consent") or "unset") != "on":
        return False
    stamp = config_stamp()
    if state.get("points_stamp") == stamp:
        return False
    try:
        breakdown: dict[str, int] | None = compute_live_points()
    except Exception as exc:  # noqa: BLE001 — ping must never affect the cycle; no stale value
        logger.warning("usage_points: Earnie-Points nicht berechenbar, sende keine Punkte: %s", exc)
        breakdown = None
    changed = _apply_points(state, breakdown)
    state["points_stamp"] = stamp
    resend = changed and breakdown is not None
    if resend:
        state.pop("last_sent_date", None)
        state.pop("last_attempt_at", None)
    up.save_state(state)
    if resend and not up.is_kill_switch_off():
        up.spawn_maybe_send_ping()
    return changed
