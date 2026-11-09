"""Wallboxes ``components.json`` ``wallboxes[]`` for the Hauskonfigurator (multi-EV M1b).

A wallbox is plant hardware: its Kennung is fixed when it is created (the EVs reference it in
``wallbox_assignment`` and its charger IDs are ``evcs.<Kennung>.*``). The Wallboxen tab edits
label, voltage, phases and current range; the charger bindings are mapped on EHAL-Com.
"""
from __future__ import annotations

from typing import Any

from house_config.id_slug import slug_id
from house_config.label_uniqueness import assert_unique_label
from house_config.wallboxes import (
    WALLBOXES_KEY,
    check_wallbox_pairs,
    evs_at_wallbox,
    normalize_wallbox,
    normalize_wallboxes,
    serialize_wallbox,
)
from runtime_store.persist_paths import resolve_house_profiles_json_path

WALLBOX_FIELDS = (
    "label",
    "voltage_v",
    "phases",
    "min_current_a",
    "max_current_a",
    "unknown_vehicle",
)


def _components() -> dict:
    from ui.house_config_entities_io import _load_components_document

    return _load_components_document()


def raw_house_document() -> dict:
    import os

    from ui.house_config_io import read_json_document

    path = resolve_house_profiles_json_path()
    return read_json_document(path) if os.path.isfile(path) else {}


def list_wallboxes() -> list[dict[str, Any]]:
    """Normalized wallboxes of ``components.json`` (file order)."""
    return normalize_wallboxes(_components().get(WALLBOXES_KEY))


def wallboxes_map() -> dict[str, dict[str, Any]]:
    return {w["id"]: w for w in list_wallboxes()}


def upsert_wallbox(fields: dict[str, Any], *, stable_id: str = "") -> str:
    """Create (``stable_id`` empty) or update a wallbox; return its Kennung.

    A new wallbox gets its Kennung from the label. An update keeps the Kennung and the
    charger bindings and fails when an EV at the wallbox would lose its common current.
    """
    from house_config.required_signal_activation import activate_wallbox_required
    from ui.house_config_entities_io import _save_components_document

    data = _components()
    raw_list = list(data.get(WALLBOXES_KEY) or [])
    current = normalize_wallboxes(raw_list)
    old_id = str(stable_id or "").strip()
    label = str(fields.get("label") or "").strip()
    if not label:
        raise ValueError("Wallbox: Bezeichnung fehlt.")
    existing = next((w for w in current if w["id"] == old_id), None)
    if old_id and existing is None:
        raise ValueError(f"Unbekannte Wallbox '{old_id}'.")
    if existing is None:
        wallbox_id = slug_id(label, existing={w["id"] for w in current})
        bindings: dict[str, str] = {}
    else:
        wallbox_id = old_id
        bindings = dict(existing.get("ehal_bindings") or {})
    assert_unique_label(label, current, exclude_id=wallbox_id)
    raw = {k: fields[k] for k in WALLBOX_FIELDS if k in fields}
    raw.update(id=wallbox_id, label=label, ehal_bindings=bindings)
    spec = normalize_wallbox(activate_wallbox_required(raw), index=len(current))
    check_wallbox_pairs(raw_house_document(), spec)
    stored = serialize_wallbox(spec)
    if existing is None:
        raw_list.append(stored)
    else:
        raw_list = [stored if str(w.get("id")) == wallbox_id else w for w in raw_list]
    _save_components_document({**data, WALLBOXES_KEY: raw_list})
    return wallbox_id


def delete_wallbox(wallbox_id: str) -> None:
    """Remove a wallbox no EV is assigned to."""
    from ui.house_config_entities_io import _save_components_document

    target = str(wallbox_id or "").strip()
    if not target:
        raise ValueError("Wallbox-Kennung fehlt.")
    data = _components()
    raw_list = list(data.get(WALLBOXES_KEY) or [])
    remaining = [w for w in raw_list if str(w.get("id") or "").strip() != target]
    if len(remaining) == len(raw_list):
        raise ValueError(f"Unbekannte Wallbox '{target}'.")
    users = evs_at_wallbox(raw_house_document(), target)
    if users:
        names = ", ".join(
            f"{ev.get('label') or ev.get('id')} (Hausprofil {pid})" for pid, ev in users
        )
        raise ValueError(
            f"Wallbox '{target}' ist noch E-Autos zugeordnet: {names}. "
            "Zuerst die E-Autos einer anderen Wallbox zuordnen."
        )
    _save_components_document({**data, WALLBOXES_KEY: remaining})
