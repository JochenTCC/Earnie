"""Read/write signals for Loxone VO/VI pilots, derived from the saved bindings.

Shared by the VO/VI template generators and the EHAL-Com push inbox. Storage is
read as saved; qualified IDs come from ``ehal.qualified_ids``. Wire titles are
derived from the qualified ID (not the Merker name).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ehal.qualified_ids import (
    field_kind,
    is_digital_id,
    qualified_battery_id,
    qualified_consumer_id,
    qualified_plant_id,
)

HEARTBEAT_ID = "heartbeat"
HEARTBEAT_TITLE = "Push_Earnie_Heartbeat"
HEARTBEAT_WRITE_ID = "heartbeat_ts"

# Kinds excluded from VO / VI generation (empty = none).
SKIP_KINDS: frozenset[str] = frozenset()
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})
_WRITE_ID_RE = re.compile(
    r"^(?:heartbeat_ts|(?:[a-z0-9_]{1,64}\.){0,2}set_[a-z0-9_]{1,64})$"
)


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


def heartbeat_write_signal() -> Signal:
    """VI heartbeat from ``status.json`` (``heartbeat_ts`` Unix seconds)."""
    return Signal(
        group="Heartbeat",
        ehal_id=HEARTBEAT_WRITE_ID,
        old_name="(Heartbeat)",
        title=vi_title_from_qualified_id(HEARTBEAT_WRITE_ID),
        digital=False,
    )


def _is_read(field: str) -> bool:
    return field_kind(field).startswith(("sens_", "get_"))


def _is_write(field: str) -> bool:
    return field_kind(field).startswith("set_")


def _sanitize_id_text(ehal_id: str) -> str:
    text = str(ehal_id).strip().translate(_UMLAUTS).replace(".", "_")
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")


def ascii_title(name: str) -> str:
    """Legacy Merker-based VO title (kept for tests / callers). Prefer ``title_from_qualified_id``."""
    text = str(name).strip().translate(_UMLAUTS)
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return f"Push_{text}" if text else "Push_unbenannt"


def title_from_qualified_id(ehal_id: str) -> str:
    """VO Cmd Title from the qualified EHAL ID (``Push_`` prefix for parallel push)."""
    text = _sanitize_id_text(ehal_id)
    return f"Push_{text}" if text else "Push_unbenannt"


def vi_title_from_qualified_id(ehal_id: str) -> str:
    """VI Cmd Title from the qualified EHAL ID (no ``Push_`` prefix)."""
    return _sanitize_id_text(ehal_id) or "unbenannt"


def is_valid_write_ehal_id(ehal_id: object) -> bool:
    """Accept bare or qualified ``set_*`` IDs and ``heartbeat_ts``."""
    return bool(_WRITE_ID_RE.match(str(ehal_id or "")))


def pilot_id(entity_kind: str, entity_id: str, field: str, consumer_type: str = "") -> str | None:
    """Qualified pilot ID for a binding key, or ``None`` if it is not pushed."""
    if field_kind(field) in SKIP_KINDS:
        return None
    if entity_kind == "battery":
        return qualified_battery_id(entity_id, field)
    if entity_kind == "consumer":
        return qualified_consumer_id(entity_id, consumer_type, field)
    if entity_kind == "plant":
        return qualified_plant_id(field)
    return field


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


def _binding_entries(house: dict, components: dict) -> list[tuple[str, str, str, str, str]]:
    """kind, id, type, field, name for plant, consumers, batteries."""
    entries: list[tuple[str, str, str, str, str]] = []
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
    return entries


def _signals_from_entries(
    entries: list[tuple[str, str, str, str, str]],
    *,
    accept_field,
    title_fn,
    validate_id,
    reject_msg: str,
) -> list[Signal]:
    signals: list[Signal] = []
    used_titles: set[str] = set()
    for kind, entity_id, ctype, field, name in entries:
        name = str(name or "").strip()
        if not accept_field(field):
            continue
        # Empty Merker = push-only activation (qualified ID is the wire path).
        ehal_id = pilot_id(kind, entity_id, field, ctype)
        if ehal_id is None:
            continue
        if not validate_id(ehal_id):
            raise ValueError(reject_msg.format(ehal_id=ehal_id, kind=kind, entity_id=entity_id))
        title = base = title_fn(ehal_id)
        suffix = 2
        while title in used_titles:
            title, suffix = f"{base}_{suffix}", suffix + 1
        used_titles.add(title)
        signals.append(
            Signal(
                group=_group_for(kind, entity_id),
                ehal_id=ehal_id,
                old_name=name or ehal_id,
                title=title,
                digital=is_digital_id(ehal_id),
            )
        )
    return signals


def read_signals_from_docs(house: dict, components: dict) -> list[Signal]:
    """Signals for every bound ``sens_*`` / ``get_*`` field of plant, consumers, batteries."""
    from runtime_store.loxone_push_inbox import is_valid_ehal_id

    return _signals_from_entries(
        _binding_entries(house, components),
        accept_field=_is_read,
        title_fn=title_from_qualified_id,
        validate_id=is_valid_ehal_id,
        reject_msg="pilot ID not accepted by the inbox: {ehal_id!r} (from {kind}:{entity_id})",
    )


def write_signals_from_docs(house: dict, components: dict) -> list[Signal]:
    """Signals for every bound ``set_*`` field of plant, consumers, batteries."""
    return _signals_from_entries(
        _binding_entries(house, components),
        accept_field=_is_write,
        title_fn=vi_title_from_qualified_id,
        validate_id=is_valid_write_ehal_id,
        reject_msg="write ID not accepted: {ehal_id!r} (from {kind}:{entity_id})",
    )
