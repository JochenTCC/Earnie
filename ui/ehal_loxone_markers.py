"""Merker-name lookups and structure-scan rows for the Loxone EHAL mapping.

Split out of ``ui.ehal_loxone_mapping`` (names stay importable from there).
``build_entity_rows`` is resolved at call time.
"""
from __future__ import annotations

from typing import Any

from ui.ehal_loxone_mapping_base import _nonempty


def _m():
    from ui import ehal_loxone_mapping

    return ehal_loxone_mapping


def configured_marker_names(house_doc: dict, profile_id: str) -> list[str]:
    names: list[str] = []
    for row in _m().build_entity_rows(house_doc, profile_id):
        names.extend(v for v in row["bindings"].values() if v)
    return names


# LoxAPP3-Probe Mapping-Tabelle column order (uuid/room/category far right).
SCAN_ROW_KEYS: tuple[str, ...] = (
    "name",
    "ehal",
    "type",
    "source",
    "room",
    "category",
    "uuid",
)


def marker_to_ehal_lookup(house_doc: dict, profile_id: str) -> dict[str, str]:
    """Reverse map Merker title → EHAL binding key from plant + consumers."""
    out: dict[str, str] = {}
    for row in _m().build_entity_rows(house_doc, profile_id):
        bindings = row.get("bindings") or {}
        if not isinstance(bindings, dict):
            continue
        for field, merker in bindings.items():
            name = _nonempty(merker)
            if name and name not in out:
                out[name] = str(field)
    return out


def device_map_ehal_by_name(device_map: dict[str, Any] | None = None) -> dict[str, str]:
    """Exact greenfield marker name → ehal_field (skips null/empty)."""
    from integrations.loxone_greenfield_import import load_device_map

    dmap = device_map if device_map is not None else load_device_map()
    out: dict[str, str] = {}
    for marker in dmap.get("markers") or []:
        if not isinstance(marker, dict):
            continue
        name = _nonempty(marker.get("name"))
        field = marker.get("ehal_field")
        if not name or field is None:
            continue
        field_s = _nonempty(field)
        if field_s:
            out[name] = field_s
    return out


def ehal_name_for_marker(
    name: str,
    house_doc: dict,
    profile_id: str,
    *,
    bindings_lookup: dict[str, str] | None = None,
    device_lookup: dict[str, str] | None = None,
) -> str:
    """Resolve EHAL wire name for a Merker: house binding first, else device map."""
    key = _nonempty(name)
    if not key:
        return ""
    reverse = (
        bindings_lookup
        if bindings_lookup is not None
        else marker_to_ehal_lookup(house_doc, profile_id)
    )
    if key in reverse:
        return reverse[key]
    dmap = device_lookup if device_lookup is not None else device_map_ehal_by_name()
    return dmap.get(key, "")


def structure_scan_row(
    *,
    name: str,
    ehal: str = "",
    type_: str = "",
    source: str = "",
    room: str = "",
    category: str = "",
    uuid: str = "",
) -> dict[str, str]:
    """Ordered Mapping-Tabelle row dict."""
    return {
        "name": name,
        "ehal": ehal,
        "type": type_,
        "source": source,
        "room": room,
        "category": category,
        "uuid": uuid,
    }


def enrich_structure_scan_rows(
    items: list[Any],
    house_doc: dict,
    profile_id: str,
) -> list[dict[str, str]]:
    """Build ordered scan rows with ehal resolved from house / device map."""
    reverse = marker_to_ehal_lookup(house_doc, profile_id)
    try:
        dmap = device_map_ehal_by_name()
    except (OSError, ValueError, FileNotFoundError):
        dmap = {}
    rows: list[dict[str, str]] = []
    for item in items:
        name, type_, source, room, category, uuid = _scan_item_fields(item)
        ehal = ehal_name_for_marker(
            name,
            house_doc,
            profile_id,
            bindings_lookup=reverse,
            device_lookup=dmap,
        )
        rows.append(
            structure_scan_row(
                name=name,
                ehal=ehal,
                type_=type_,
                source=source,
                room=room,
                category=category,
                uuid=uuid,
            )
        )
    return rows


def _scan_item_fields(item: Any) -> tuple[str, str, str, str, str, str]:
    """Extract name/type/source/room/category/uuid from StructureItem or dict."""
    keys = ("name", "type", "source", "room", "category", "uuid")
    if isinstance(item, dict):
        vals = [_nonempty(item.get(k)) for k in keys]
    else:
        vals = [_nonempty(getattr(item, k, "")) for k in keys]
    return (vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])
