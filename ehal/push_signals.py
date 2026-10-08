"""Read signals expected from a Loxone push pilot, derived from the saved bindings.

Pilot (spike/vo-push-pilot). Shared by the VO template generator (which turns them
into Virtual Output commands) and the EHAL-Com push inbox (which shows which expected
signals have not arrived). Storage is read as saved; qualified IDs come from
``ehal.qualified_ids``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ehal.qualified_ids import (
    field_kind,
    is_digital_id,
    qualified_battery_id,
    qualified_consumer_id,
)

HEARTBEAT_ID = "heartbeat"
HEARTBEAT_TITLE = "Push_Earnie_Heartbeat"

# Kinds excluded from VO push generation (meter energy handled separately).
SKIP_KINDS: frozenset[str] = frozenset()
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


@dataclass(frozen=True)
class Signal:
    group: str
    ehal_id: str
    old_name: str
    title: str
    digital: bool


def heartbeat_signal() -> Signal:
    """Constant non-zero signal that proves the Miniserver link is alive."""
    return Signal(
        group="Heartbeat",
        ehal_id=HEARTBEAT_ID,
        old_name="(Heartbeat)",
        title=HEARTBEAT_TITLE,
        digital=False,
    )


def _is_read(field: str) -> bool:
    return field_kind(field).startswith(("sens_", "get_"))


def ascii_title(name: str) -> str:
    text = str(name).strip().translate(_UMLAUTS)
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return f"Push_{text}" if text else "Push_unbenannt"


def pilot_id(entity_kind: str, entity_id: str, field: str, consumer_type: str = "") -> str | None:
    """Qualified pilot ID for a binding key, or ``None`` if it is not pushed."""
    if field_kind(field) in SKIP_KINDS:
        return None
    if entity_kind == "battery":
        return qualified_battery_id(entity_id, field)
    if entity_kind == "consumer":
        return qualified_consumer_id(entity_id, consumer_type, field)
    return field  # plant: house-wide bare field names


def _group_for(entity_kind: str, entity_id: str) -> str:
    if entity_kind == "plant":
        return "Plant"
    if entity_kind == "battery":
        return f"Batterie_{entity_id}"
    if entity_id in ("pool_swimspa", "pool_filter"):
        return "Pool"
    if entity_id == "waermepumpe":
        return "Waermepumpe"
    if entity_id == "e_auto":
        return "EV"
    return "Verbraucher"


def read_signals_from_docs(house: dict, components: dict) -> list[Signal]:
    """Signals for every bound ``sens_*`` / ``get_*`` field of plant, consumers, batteries."""
    from runtime_store.loxone_push_inbox import is_valid_ehal_id

    entries: list[tuple[str, str, str, str, str]] = []  # kind, id, type, field, name
    for field, name in ((house.get("plant") or {}).get("ehal_bindings") or {}).items():
        entries.append(("plant", "plant", "", field, name))
    profiles = house.get("profiles") or {}
    for profile in profiles.values() if isinstance(profiles, dict) else profiles:
        for consumer in profile.get("consumers", []):
            for field, name in (consumer.get("ehal_bindings") or {}).items():
                entries.append(
                    ("consumer", str(consumer.get("id")), str(consumer.get("type") or ""), field, name)
                )
    for battery in components.get("batteries", []):
        for field, name in (battery.get("ehal_bindings") or {}).items():
            entries.append(("battery", str(battery.get("id")), "", field, name))

    signals: list[Signal] = []
    used_titles: set[str] = set()
    for kind, entity_id, ctype, field, name in entries:
        name = str(name or "").strip()
        if not name or not _is_read(field):
            continue
        ehal_id = pilot_id(kind, entity_id, field, ctype)
        if ehal_id is None:
            continue
        if not is_valid_ehal_id(ehal_id):
            raise ValueError(f"pilot ID not accepted by the inbox: {ehal_id!r} (from {kind}:{entity_id})")
        title = base = ascii_title(name)
        suffix = 2
        while title in used_titles:
            title, suffix = f"{base}_{suffix}", suffix + 1
        used_titles.add(title)
        signals.append(
            Signal(
                group=_group_for(kind, entity_id),
                ehal_id=ehal_id,
                old_name=name,
                title=title,
                digital=is_digital_id(ehal_id),
            )
        )
    return signals
