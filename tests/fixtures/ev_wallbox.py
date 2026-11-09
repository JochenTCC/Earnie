"""Test helper: old inline EV shape (data model 5) → real file shape (data model 6).

Tests often write an EV consumer inline in the old shape (``nominal_power_kw``,
``min_power_kw``, voltage / phases in ``charging_schedule``, charger bindings on the EV).
``split_inline_wallboxes`` runs the real ``dm6.wallboxes`` step on it: the EV gets currents and
``wallbox_assignment``, the charger moves to a wallbox entry for ``components.json``. The loaded
consumer keeps the old ``nominal_power_kw`` / ``min_power_kw`` through the pair view.
"""
from __future__ import annotations

import copy
from typing import Any

from house_config.wallboxes import WALLBOXES_KEY, wallboxes_by_id


def split_inline_wallboxes(doc: dict) -> tuple[dict, list[dict[str, Any]]]:
    """(house document in file shape, raw wallbox entries)."""
    from runtime_store.migration.steps.wallboxes import apply, detect

    house = copy.deepcopy(doc)
    docs = {"house_profiles.json": house, "components.json": {WALLBOXES_KEY: []}}
    if not detect(docs):
        return house, []
    result = apply(docs, {})
    assert not result.blockers, result.blockers
    return (
        result.docs["house_profiles.json"],
        list(result.docs["components.json"].get(WALLBOXES_KEY) or []),
    )


def inline_wallbox_catalog(doc: dict) -> tuple[dict, dict[str, dict]]:
    """(house document, normalized wallboxes by id) for ``normalize_house_profiles_document``."""
    out, entries = split_inline_wallboxes(doc)
    return out, wallboxes_by_id({WALLBOXES_KEY: entries})


def merge_wallboxes(components: dict, entries: list[dict[str, Any]]) -> dict:
    """``components`` with ``entries`` added (same id replaced)."""
    out = dict(components)
    ids = {e["id"] for e in entries}
    kept = [w for w in out.get(WALLBOXES_KEY) or [] if w.get("id") not in ids]
    if kept or entries:
        out[WALLBOXES_KEY] = kept + list(entries)
    return out


def wallbox_entry(
    wallbox_id: str,
    *,
    voltage_v: float = 230.0,
    phases: int = 3,
    min_current_a: float = 6.0,
    max_current_a: float = 32.0,
    ehal_bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Raw ``components.json`` wallbox entry (data model 6)."""
    return {
        "id": wallbox_id,
        "label": f"Wallbox {wallbox_id}",
        "voltage_v": voltage_v,
        "phases": phases,
        "min_current_a": min_current_a,
        "max_current_a": max_current_a,
        "ehal_bindings": dict(ehal_bindings or {}),
    }


def wallbox_catalog(*entries: dict[str, Any]) -> dict[str, dict]:
    """Normalized wallboxes by id, as ``normalize_house_profiles_document`` takes them."""
    return wallboxes_by_id({WALLBOXES_KEY: list(entries)})


def ev_fields(
    wallbox_id: str,
    *,
    phases: int = 3,
    min_current_a: float = 6.0,
    max_current_a: float = 16.0,
) -> dict[str, Any]:
    """Current fields and fixed assignment of a raw data-model-6 EV consumer."""
    return {
        "phases": phases,
        "min_current_a": min_current_a,
        "max_current_a": max_current_a,
        "wallbox_assignment": {"mode": "fixed", "wallbox_id": wallbox_id},
    }
