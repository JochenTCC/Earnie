"""Test helper: old inline thermal_annual shape → real file shape.

Tests often write a house profile inline in the old shape (``heat_source`` and the building
fields on the consumer). ``split_inline_heating`` moves the generation fields into a catalog
the way the house configurator does (``heating_<profile_id>``) and the building fields to the
house profile (``dm5.house_thermal``: ``heating_enabled``, ``thermal``, ``persons``), so the
loader sees the real file shape. An old-shape ``nominal_power_kw`` (electric power) becomes
``heating_power_kw`` as in ``dm5.heating_power``, so the loaded consumer keeps that
``nominal_power_kw``.
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


def _hoist_building_fields(doc: dict) -> dict:
    from runtime_store.migration.steps.house_thermal import apply

    if not any("heating_enabled" not in p for p in _profiles(doc)):
        return doc
    result = apply({"house_profiles.json": doc}, {})
    assert not result.blockers, result.blockers
    return result.docs["house_profiles.json"]


# Input power the year model used for a thermal_annual consumer without nominal_power_kw
# before heating_power_kw existed; old-shape test data keeps its results with it.
LEGACY_INPUT_POWER_KW = 3.0


def _heating_power_entry(entry: dict[str, Any]) -> dict[str, Any]:
    from runtime_store.migration.steps.heating_power import convert_entry

    return convert_entry(entry)


def legacy_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Catalog entry in the old shape (``nominal_power_kw`` or none) → current shape.

    Same conversion as ``dm5.heating_power``; a missing or zero power is the old effective
    ``LEGACY_INPUT_POWER_KW``, so the loader derives the same input power as before.
    """
    if "heating_power_kw" in entry:
        return dict(entry)
    nominal = float(entry.get("nominal_power_kw") or 0.0) or LEGACY_INPUT_POWER_KW
    return _heating_power_entry({**entry, "nominal_power_kw": nominal})


def split_inline_heating(doc: dict) -> tuple[dict, list[dict[str, Any]]]:
    """(house document in file shape, raw catalog entries)."""
    out = _hoist_building_fields(copy.deepcopy(doc))
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
            nominal = consumer.get("nominal_power_kw")
            item, entry = split_inline_heating_system(
                consumer, system_id=system_id, label=system_id
            )
            if "heating_power_kw" not in entry:
                entry = legacy_entry({**entry, "nominal_power_kw": nominal})
            consumers[index] = item
            entries.append(entry)
    return out, entries


def inline_heating_catalog(doc: dict) -> tuple[dict, dict[str, dict]]:
    """(house document, normalized catalog by id) for ``normalize_house_profiles_document``."""
    out, entries = split_inline_heating(doc)
    return out, heating_systems_by_id({"heating_systems": entries})


def normalize_inline_house(doc: dict) -> dict:
    """Old inline heating and EV shape → loader; catalogs passed like the file loader does."""
    from house_config.profiles_store import normalize_house_profiles_document
    from tests.fixtures.ev_wallbox import inline_wallbox_catalog

    out, catalog = inline_heating_catalog(doc)
    out, wallboxes = inline_wallbox_catalog(out)
    return normalize_house_profiles_document(out, heating_systems=catalog, wallboxes=wallboxes)


def write_inline_pack(config_dir, doc: dict, *, components: dict | None = None) -> None:
    """Write ``house_profiles.json`` + ``components.json`` (catalog merged into ``components``)."""
    import json
    from pathlib import Path

    root = Path(config_dir)
    root.mkdir(parents=True, exist_ok=True)
    from tests.fixtures.ev_wallbox import merge_wallboxes, split_inline_wallboxes

    out, entries = split_inline_heating(doc)
    out, wallboxes = split_inline_wallboxes(out)
    comp = copy.deepcopy(components) if components is not None else {}
    comp.setdefault("heating_systems", []).extend(entries)
    comp = merge_wallboxes(comp, wallboxes)
    (root / "house_profiles.json").write_text(json.dumps(out), encoding="utf-8")
    (root / "components.json").write_text(json.dumps(comp), encoding="utf-8")


def _merge_into_sibling_components(
    house_path, entries: list[dict[str, Any]], wallboxes: list[dict[str, Any]] | None = None
) -> None:
    import json
    from pathlib import Path

    from tests.fixtures.ev_wallbox import merge_wallboxes

    comp_path = Path(house_path).with_name("components.json")
    comp = json.loads(comp_path.read_text(encoding="utf-8")) if comp_path.is_file() else {}
    catalog = [e for e in comp.get("heating_systems") or [] if e["id"] not in {x["id"] for x in entries}]
    comp["heating_systems"] = catalog + entries
    comp = merge_wallboxes(comp, wallboxes or [])
    comp_path.write_text(json.dumps(comp), encoding="utf-8")


def write_inline_house(path, doc: dict) -> None:
    """Write ``house_profiles.json`` and merge its catalog into the sibling ``components.json``."""
    import json
    from pathlib import Path

    from tests.fixtures.ev_wallbox import split_inline_wallboxes

    out, entries = split_inline_heating(doc)
    out, wallboxes = split_inline_wallboxes(out)
    Path(path).write_text(json.dumps(out), encoding="utf-8")
    _merge_into_sibling_components(path, entries, wallboxes)


def save_inline_house(path, doc: dict) -> None:
    """``save_house_profiles_document`` for a document with inline heat generation."""
    from house_config.profiles_store import save_house_profiles_document

    from tests.fixtures.ev_wallbox import split_inline_wallboxes

    out, entries = split_inline_heating(doc)
    out, wallboxes = split_inline_wallboxes(out)
    _merge_into_sibling_components(path, entries, wallboxes)
    save_house_profiles_document(str(path), out)
