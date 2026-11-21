"""Rekey wallbox charger bindings to the qualified spelling ``evcs.<Wallbox>.<kind>``.

A wallbox could hold a charger kind under two keys: the bare ``<kind>`` (or the moved EV's
``evcs.<E-Auto>.<kind>``) that ``dm6.wallboxes`` carried over from the EV, and the qualified
``evcs.<Wallbox>.<kind>`` the required-signal activation added next to it. The qualified form
is the one the signal catalog, the push inbox and the wallbox editor use. This merges every
charger key of a wallbox into it: a Merker in either key is kept; two different Merker names
are a conflict for the user.
"""
from __future__ import annotations

import copy
from typing import Any

from ehal.qualified_ids import NS_EVCS, field_kind


def canonical_charger_key(wallbox_id: str, key: str) -> str:
    return f"{NS_EVCS}.{wallbox_id}.{field_kind(str(key))}"


def _off_spelling_keys(wallbox: dict) -> list[str]:
    """Charger keys of ``wallbox`` that are not ``evcs.<its Kennung>.<kind>``."""
    wallbox_id = str(wallbox.get("id") or "").strip()
    bindings = wallbox.get("ehal_bindings")
    if not wallbox_id or not isinstance(bindings, dict):
        return []
    return [
        str(key) for key in bindings if str(key) != canonical_charger_key(wallbox_id, key)
    ]


def components_have_off_spelling_charger_keys(components: dict | None) -> bool:
    if not isinstance(components, dict):
        return False
    return any(
        _off_spelling_keys(wallbox)
        for wallbox in components.get("wallboxes") or []
        if isinstance(wallbox, dict)
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def migrate_wallbox_charger_keys(components: dict) -> tuple[dict, bool, list[str]]:
    """Return ``(components, changed, conflicts)``; on conflicts the input is returned unchanged."""
    out = copy.deepcopy(components)
    changed = False
    conflicts: list[str] = []
    for wallbox in out.get("wallboxes") or []:
        if not isinstance(wallbox, dict):
            continue
        keys = _off_spelling_keys(wallbox)
        if not keys:
            continue
        wallbox_id = str(wallbox["id"]).strip()
        bindings = dict(wallbox["ehal_bindings"])
        for key in keys:
            target = canonical_charger_key(wallbox_id, key)
            moved_value = _text(bindings.pop(key))
            kept_value = _text(bindings.get(target))
            if moved_value and kept_value and moved_value != kept_value:
                conflicts.append(
                    f"Wallbox '{wallbox_id}': {field_kind(key)} ist zweimal gemappt "
                    f"('{kept_value}' unter {target} und '{moved_value}' unter {key}). "
                    "Bitte im EHAL-Mapping einen der beiden Merker entfernen."
                )
                continue
            bindings[target] = kept_value or moved_value
        wallbox["ehal_bindings"] = bindings
        changed = True
    if conflicts:
        return components, False, conflicts
    return out, changed, []
