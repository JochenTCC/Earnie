"""Persist single_use powerstation reserve state (2.7.g)."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

FILENAME = "powerstation_reserves.json"

STATE_EMPTY = "empty"
STATE_CHARGING = "charging"
STATE_STANDBY = "standby"
STATE_DISCHARGING = "discharging"

_VALID_STATES = frozenset(
    {STATE_EMPTY, STATE_CHARGING, STATE_STANDBY, STATE_DISCHARGING}
)


def _path() -> str:
    return runtime_path(FILENAME)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def load_reserve_states() -> dict[str, dict[str, Any]]:
    path = _path()
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: powerstation_reserves muss ein Objekt sein.")
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        out[str(key)] = dict(value)
    return out


def save_reserve_states(states: dict[str, dict[str, Any]]) -> None:
    path = _path()
    _ensure_parent(path)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(states, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def default_state(target_kwh: float) -> dict[str, Any]:
    return {
        "state": STATE_EMPTY,
        "stored_kwh": 0.0,
        "target_kwh": float(target_kwh),
        "trigger_active": False,
    }


def get_or_init_state(
    states: dict[str, dict[str, Any]],
    powerstation_id: str,
    *,
    target_kwh: float,
) -> dict[str, Any]:
    entry = states.get(powerstation_id)
    if entry is None:
        entry = default_state(target_kwh)
        states[powerstation_id] = entry
        return entry
    entry["target_kwh"] = float(target_kwh)
    state = str(entry.get("state") or STATE_EMPTY)
    if state not in _VALID_STATES:
        entry["state"] = STATE_EMPTY
    entry["stored_kwh"] = max(0.0, float(entry.get("stored_kwh") or 0.0))
    entry["trigger_active"] = bool(entry.get("trigger_active"))
    return entry


def set_trigger(powerstation_id: str, *, active: bool) -> dict[str, Any]:
    states = load_reserve_states()
    entry = get_or_init_state(states, powerstation_id, target_kwh=0.0)
    entry["trigger_active"] = bool(active)
    if active and entry["state"] in (STATE_STANDBY, STATE_CHARGING, STATE_EMPTY):
        entry["state"] = STATE_DISCHARGING
    elif not active and entry["state"] == STATE_DISCHARGING:
        entry["state"] = STATE_EMPTY
        entry["stored_kwh"] = 0.0
    save_reserve_states(states)
    return entry
