"""Persist single_use powerstation reserve state (2.7.g / 2.7.p)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

FILENAME = "powerstation_reserves.json"

STATE_EMPTY = "empty"
STATE_CHARGING = "charging"
STATE_STANDBY = "standby"
STATE_DISCHARGING = "discharging"

REFILL_DEADLINE_H = 24.0

_VALID_STATES = frozenset(
    {STATE_EMPTY, STATE_CHARGING, STATE_STANDBY, STATE_DISCHARGING}
)


def _path() -> str:
    return runtime_path(FILENAME)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(raw: object) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
        "refill_opened_at": None,
    }


def ensure_refill_opened(entry: dict[str, Any], *, now: datetime | None = None) -> None:
    """Stamp refill clock when entering empty/charging without an open deadline."""
    state = str(entry.get("state") or STATE_EMPTY)
    if state not in (STATE_EMPTY, STATE_CHARGING):
        return
    if _parse_iso(entry.get("refill_opened_at")) is not None:
        return
    stamp = now or _utc_now()
    entry["refill_opened_at"] = stamp.astimezone(timezone.utc).isoformat()


def clear_refill_opened(entry: dict[str, Any]) -> None:
    entry["refill_opened_at"] = None


def refill_deadline_utc(entry: dict[str, Any]) -> datetime | None:
    opened = _parse_iso(entry.get("refill_opened_at"))
    if opened is None:
        return None
    return opened + timedelta(hours=REFILL_DEADLINE_H)


def get_or_init_state(
    states: dict[str, dict[str, Any]],
    powerstation_id: str,
    *,
    target_kwh: float,
    update_target: bool = True,
) -> dict[str, Any]:
    """Return reserve entry, creating it when missing.

    ``update_target=True`` (default) refreshes ``target_kwh`` from the caller —
    used by ``collect_active_reserves`` / learning. Slot advance and trigger
    latch must pass ``update_target=False`` so a placeholder ``0.0`` cannot wipe
    a filled carve-out target (prod: virtual_gs stayed empty after MILP charge).
    """
    entry = states.get(powerstation_id)
    if entry is None:
        entry = default_state(target_kwh)
        states[powerstation_id] = entry
        ensure_refill_opened(entry)
        return entry
    if update_target:
        entry["target_kwh"] = float(target_kwh)
    state = str(entry.get("state") or STATE_EMPTY)
    if state not in _VALID_STATES:
        entry["state"] = STATE_EMPTY
    entry["stored_kwh"] = max(0.0, float(entry.get("stored_kwh") or 0.0))
    entry["trigger_active"] = bool(entry.get("trigger_active"))
    if "refill_opened_at" not in entry:
        entry["refill_opened_at"] = None
    ensure_refill_opened(entry)
    return entry


def set_trigger(powerstation_id: str, *, active: bool) -> dict[str, Any]:
    """Manual / live release latch.

    ``active=True`` moves to discharging (floor released).
    ``active=False`` is an explicit UI reset: wipe storage and reopen refill
    (auto inactive must **not** call this — leftover drain stays in discharging).
    """
    states = load_reserve_states()
    entry = get_or_init_state(
        states, powerstation_id, target_kwh=0.0, update_target=False
    )
    entry["trigger_active"] = bool(active)
    if active and entry["state"] in (STATE_STANDBY, STATE_CHARGING, STATE_EMPTY):
        entry["state"] = STATE_DISCHARGING
        clear_refill_opened(entry)
    elif not active and entry["state"] == STATE_DISCHARGING:
        entry["state"] = STATE_EMPTY
        entry["stored_kwh"] = 0.0
        entry["refill_opened_at"] = None
        ensure_refill_opened(entry)
    save_reserve_states(states)
    return entry
