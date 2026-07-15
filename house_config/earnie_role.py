"""Explizite Earnie-Rolle für generic-Verbraucher (known / flex / manual)."""
from __future__ import annotations

import math

EARNIE_ROLE_KNOWN = "known"
EARNIE_ROLE_FLEX = "flex"
EARNIE_ROLE_MANUAL = "manual"
EARNIE_ROLES = frozenset({EARNIE_ROLE_KNOWN, EARNIE_ROLE_FLEX, EARNIE_ROLE_MANUAL})
DEFAULT_MANUAL_HORIZON_H = 6.0


def infer_earnie_role_from_legacy(consumer: dict) -> str:
    """Leitet Rolle aus Legacy-Feldern ab (Migration / unspeicherte Rohdaten)."""
    if isinstance(consumer.get("appliance_recommendation"), dict):
        return EARNIE_ROLE_MANUAL
    schedule = consumer.get("schedule") or {}
    if int(schedule.get("runs_per_week", 0) or 0) <= 0:
        return EARNIE_ROLE_KNOWN
    shift = float(schedule.get("start_shift_h", 0.0) or 0.0)
    if shift > 0:
        return EARNIE_ROLE_FLEX
    return EARNIE_ROLE_KNOWN


def resolve_earnie_role(consumer: dict) -> str:
    """Gültige Rolle für einen generic-Verbraucher."""
    explicit = str(consumer.get("earnie_role", "") or "").strip().lower()
    if explicit in EARNIE_ROLES:
        return explicit
    return infer_earnie_role_from_legacy(consumer)


def is_earnie_known(consumer: dict) -> bool:
    return resolve_earnie_role(consumer) == EARNIE_ROLE_KNOWN


def is_earnie_flex(consumer: dict) -> bool:
    return resolve_earnie_role(consumer) == EARNIE_ROLE_FLEX


def is_earnie_manual(consumer: dict) -> bool:
    return resolve_earnie_role(consumer) == EARNIE_ROLE_MANUAL


def manual_recommendation_horizon_h(consumer: dict) -> int:
    """Empfehlungshorizont (h) für Manuelle Geräte aus schedule.start_shift_h."""
    schedule = consumer.get("schedule") or {}
    shift = float(schedule.get("start_shift_h", DEFAULT_MANUAL_HORIZON_H) or DEFAULT_MANUAL_HORIZON_H)
    return max(1, int(math.ceil(shift)))
