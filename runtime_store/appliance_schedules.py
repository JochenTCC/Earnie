"""Persistente Startpläne manueller Geräte (runtime/appliance_schedules.json)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import config
from data.planning_window import align_to_planning_timezone
from runtime_store.persist_paths import runtime_path

logger = logging.getLogger(__name__)

SCHEDULES_FILENAME = "appliance_schedules.json"


def _schedules_path() -> str:
    return runtime_path(SCHEDULES_FILENAME)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _atomic_replace_unavailable(exc: OSError) -> bool:
    """True wenn tmp→Ziel nicht atomar ersetzt werden kann (SMB/UNC, Synology)."""
    if getattr(exc, "errno", None) in (13, 16):
        return True
    return getattr(exc, "winerror", None) == 5


def _write_json_direct(path: str, data: dict[str, Any]) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def _save_json(path: str, data: dict[str, Any]) -> None:
    """Atomar schreiben; bei SMB/UNC-Fallback direkt in die Zieldatei."""
    _ensure_parent(path)
    tmp = f"{path}.tmp"
    try:
        _write_json_direct(tmp, data)
        os.replace(tmp, path)
    except OSError as exc:
        if not _atomic_replace_unavailable(exc):
            raise
        logger.warning(
            "appliance_schedules: atomares Schreiben nach %s nicht möglich (%s), "
            "direkter Versuch",
            path,
            exc,
        )
        _write_json_direct(path, data)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return align_to_planning_timezone(parsed, config.get_planning_timezone())


def load_schedules() -> dict[str, dict[str, Any]]:
    path = _schedules_path()
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: appliance_schedules muss ein Objekt sein.")
    return _remap_schedule_keys(raw)


def _canonical_appliance_id(appliance_id: str) -> str:
    for appliance in config.get_appliances():
        canonical = str(appliance["id"])
        legacy = str(appliance.get("legacy_id", "")).strip()
        if appliance_id == canonical or (legacy and appliance_id == legacy):
            return canonical
    return str(appliance_id)


def _remap_schedule_keys(schedules: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    remapped: dict[str, dict[str, Any]] = {}
    for key, entry in schedules.items():
        remapped[_canonical_appliance_id(key)] = entry
    return remapped


def save_schedule(
    appliance_id: str,
    *,
    start_at: datetime,
    power_kw: float,
    runtime_h: float,
) -> dict[str, Any]:
    if power_kw <= 0:
        raise ValueError("power_kw muss > 0 sein.")
    if runtime_h <= 0:
        raise ValueError("runtime_h muss > 0 sein.")
    start = align_to_planning_timezone(start_at, config.get_planning_timezone())
    expires = start + timedelta(hours=float(runtime_h))
    entry = {
        "start_at": start.isoformat(timespec="seconds"),
        "power_kw": round(float(power_kw), 3),
        "runtime_h": round(float(runtime_h), 3),
        "expires_at": expires.isoformat(timespec="seconds"),
    }
    schedules = load_schedules()
    schedules[str(_canonical_appliance_id(appliance_id))] = entry
    _save_json(_schedules_path(), schedules)
    return entry


def remove_schedule(appliance_id: str) -> None:
    schedules = load_schedules()
    canonical = _canonical_appliance_id(appliance_id)
    if canonical not in schedules:
        return
    schedules.pop(canonical, None)
    _save_json(_schedules_path(), schedules)


def purge_expired(now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """Entfernt abgelaufene Pläne; gibt verbleibende Schedules zurück."""
    current = align_to_planning_timezone(
        now or datetime.now().astimezone(), config.get_planning_timezone()
    )
    schedules = load_schedules()
    kept: dict[str, dict[str, Any]] = {}
    for appliance_id, entry in schedules.items():
        expires_raw = entry.get("expires_at")
        if not expires_raw:
            continue
        expires = _parse_iso(str(expires_raw))
        if current < expires:
            kept[appliance_id] = entry
    if kept != schedules:
        _save_json(_schedules_path(), kept)
    return kept


def active_schedule_for(appliance_id: str) -> dict[str, Any] | None:
    schedules = purge_expired()
    return schedules.get(_canonical_appliance_id(appliance_id))
