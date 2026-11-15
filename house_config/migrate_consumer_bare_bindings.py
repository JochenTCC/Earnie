"""Rekey qualified heat / pool read kinds to the bare spelling the mapping UI stores.

The signal list used to activate ``heatpump.<Kennung>.<kind>`` / ``pool.<Kennung>.<kind>``
for kinds the mapping UI stores bare (``house_config.ehal_bindings.consumer_bare_stored_kinds``).
A consumer could then hold one kind under two keys. This merges them into the bare key:
a Merker in either key is kept; two different Merker names are a conflict for the user.
"""
from __future__ import annotations

import copy
from typing import Any

from ehal.qualified_ids import field_kind, parse_qualified_id
from house_config.ehal_bindings import _profiles_iterable, consumer_bare_stored_kinds


def _qualified_bare_keys(consumer: dict) -> list[str]:
    """Qualified keys of ``consumer`` whose kind belongs under the bare spelling."""
    bindings = consumer.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return []
    bare_kinds = consumer_bare_stored_kinds(str(consumer.get("type") or ""))
    out: list[str] = []
    for key in bindings:
        parsed = parse_qualified_id(str(key))
        if parsed is None or parsed.is_plant_bare:
            continue
        if field_kind(str(key)) in bare_kinds:
            out.append(str(key))
    return out


def house_has_qualified_bare_bindings(house: dict | None) -> bool:
    if not isinstance(house, dict):
        return False
    return any(
        _qualified_bare_keys(consumer)
        for profile in _profiles_iterable(house)
        for consumer in profile.get("consumers") or []
        if isinstance(consumer, dict)
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def migrate_house_bare_bindings(house: dict) -> tuple[dict, bool, list[str]]:
    """Return ``(house, changed, conflicts)``; on conflicts the input is returned unchanged."""
    out = copy.deepcopy(house)
    changed = False
    conflicts: list[str] = []
    for profile in _profiles_iterable(out):
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict):
                continue
            keys = _qualified_bare_keys(consumer)
            if not keys:
                continue
            bindings = dict(consumer["ehal_bindings"])
            for key in keys:
                kind = field_kind(key)
                qualified_value = _text(bindings.pop(key))
                bare_value = _text(bindings.get(kind))
                if qualified_value and bare_value and qualified_value != bare_value:
                    conflicts.append(
                        f"Verbraucher '{consumer.get('id')}': {kind} ist zweimal gemappt "
                        f"('{bare_value}' und '{qualified_value}' unter {key}). Bitte im "
                        "EHAL-Mapping einen der beiden Merker entfernen."
                    )
                    continue
                bindings[kind] = bare_value or qualified_value
            consumer["ehal_bindings"] = bindings
            changed = True
    if conflicts:
        return house, False, conflicts
    return out, changed, []
