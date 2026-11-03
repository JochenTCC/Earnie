"""Test helper: inline heat generation on thermal_annual consumers → heating-system catalog.

Tests often write a house profile inline in the old shape (``heat_source`` on the consumer).
``split_inline_heating`` moves those fields into a catalog the way the house configurator
does (``heating_<profile_id>``), so the loader sees the real file shape.
"""
from __future__ import annotations

import copy
from typing import Any

from house_config.heating_systems import (
    HEATING_SYSTEM_ID_KEY,
    heating_systems_by_id,
    reference_system_id,
    split_inline_heating_system,
)


def _profiles(doc: dict) -> list[dict]:
    profiles = doc.get("profiles")
    if isinstance(profiles, dict):
        return list(profiles.values())
    return list(profiles or [])


def split_inline_heating(doc: dict) -> tuple[dict, list[dict[str, Any]]]:
    """(house document without inline generation fields, raw catalog entries)."""
    out = copy.deepcopy(doc)
    entries: list[dict[str, Any]] = []
    taken: set[str] = set()
    for profile in _profiles(out):
        consumers = profile.get("consumers") or []
        for index, consumer in enumerate(consumers):
            if not isinstance(consumer, dict) or consumer.get("type") != "thermal_annual":
                continue
            if HEATING_SYSTEM_ID_KEY in consumer and "heat_source" not in consumer:
                continue
            system_id = consumer.get(HEATING_SYSTEM_ID_KEY) or reference_system_id(
                str(profile.get("id") or "haus"), taken
            )
            taken.add(system_id)
            item, entry = split_inline_heating_system(
                consumer, system_id=system_id, label=system_id
            )
            consumers[index] = item
            entries.append(entry)
    return out, entries


def inline_heating_catalog(doc: dict) -> tuple[dict, dict[str, dict]]:
    """(house document, normalized catalog by id) for ``normalize_house_profiles_document``."""
    out, entries = split_inline_heating(doc)
    return out, heating_systems_by_id({"heating_systems": entries})


def normalize_inline_house(doc: dict) -> dict:
    from house_config.profiles_store import normalize_house_profiles_document

    out, catalog = inline_heating_catalog(doc)
    return normalize_house_profiles_document(out, heating_systems=catalog)


def write_inline_pack(config_dir, doc: dict, *, components: dict | None = None) -> None:
    """Write ``house_profiles.json`` + ``components.json`` (catalog merged into ``components``)."""
    import json
    from pathlib import Path

    root = Path(config_dir)
    root.mkdir(parents=True, exist_ok=True)
    out, entries = split_inline_heating(doc)
    comp = copy.deepcopy(components) if components is not None else {}
    comp.setdefault("heating_systems", []).extend(entries)
    (root / "house_profiles.json").write_text(json.dumps(out), encoding="utf-8")
    (root / "components.json").write_text(json.dumps(comp), encoding="utf-8")


def _merge_into_sibling_components(house_path, entries: list[dict[str, Any]]) -> None:
    import json
    from pathlib import Path

    comp_path = Path(house_path).with_name("components.json")
    comp = json.loads(comp_path.read_text(encoding="utf-8")) if comp_path.is_file() else {}
    catalog = [e for e in comp.get("heating_systems") or [] if e["id"] not in {x["id"] for x in entries}]
    comp["heating_systems"] = catalog + entries
    comp_path.write_text(json.dumps(comp), encoding="utf-8")


def write_inline_house(path, doc: dict) -> None:
    """Write ``house_profiles.json`` and merge its catalog into the sibling ``components.json``."""
    import json
    from pathlib import Path

    out, entries = split_inline_heating(doc)
    Path(path).write_text(json.dumps(out), encoding="utf-8")
    _merge_into_sibling_components(path, entries)


def save_inline_house(path, doc: dict) -> None:
    """``save_house_profiles_document`` for a document with inline heat generation."""
    from house_config.profiles_store import save_house_profiles_document

    out, entries = split_inline_heating(doc)
    _merge_into_sibling_components(path, entries)
    save_house_profiles_document(str(path), out)
