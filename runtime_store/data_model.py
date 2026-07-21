"""Earnie config data-model versioning for save/load packs."""
from __future__ import annotations

from typing import Any, Callable

CURRENT_DATA_MODEL = 3
COMPATIBLE_DATA_MODELS: frozenset[int] = frozenset({1, 2, 3})

DATA_MODEL_KEY = "earnie_data_model"

_LEGACY_SIM_BLOCK = "file_paths_battery_simulation"
_SIM_BLOCK = "scenario_explorer_conf"
_REMOVED_PATH_KEYS = ("path_consumption", "path_production")


class DataModelError(ValueError):
    """Raised when a document's data-model version is unsupported."""


def stamp_data_model(doc: dict[str, Any]) -> dict[str, Any]:
    """Ensure ``earnie_data_model`` is set to the current version."""
    doc[DATA_MODEL_KEY] = CURRENT_DATA_MODEL
    return doc


def read_data_model(doc: dict[str, Any] | None) -> int | None:
    if not isinstance(doc, dict):
        return None
    raw = doc.get(DATA_MODEL_KEY)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_config_document(doc: dict[str, Any]) -> bool:
    """True when ``doc`` looks like config.json (not tariffs/house_profiles/…)."""
    if _SIM_BLOCK in doc or _LEGACY_SIM_BLOCK in doc:
        return True
    return "live_scenario_id" in doc and "loxone_blocks" in doc


def migrate_config_document_to_v3(doc: dict[str, Any]) -> bool:
    """
    In-place v2→v3 structural fixes for config.json.

    - Rename ``file_paths_battery_simulation`` → ``scenario_explorer_conf``
    - Drop ``path_consumption`` / ``path_production`` inside that block

    Returns True if the document was mutated.
    """
    changed = False
    if _LEGACY_SIM_BLOCK in doc:
        legacy = doc.pop(_LEGACY_SIM_BLOCK)
        if _SIM_BLOCK not in doc and isinstance(legacy, dict):
            doc[_SIM_BLOCK] = legacy
        changed = True
    block = doc.get(_SIM_BLOCK)
    if isinstance(block, dict):
        for key in _REMOVED_PATH_KEYS:
            if key in block:
                del block[key]
                changed = True
    return changed


# Future: map from unsupported source version → callable that mutates in place.
_CONVERTERS: dict[int, Callable[[dict[str, Any]], None]] = {}


def ensure_compatible(doc: dict[str, Any], *, label: str) -> int:
    """
    Validate / convert a document to a compatible data-model version.

    Missing tag is treated as version 1 (legacy files before tagging).
    Older compatible versions are upgraded in-memory to CURRENT_DATA_MODEL.
    Config documents also get structural v3 migrations (rename + path-pair strip).
    """
    version = read_data_model(doc)
    if version is None:
        version = 1
        doc[DATA_MODEL_KEY] = version
    if version in COMPATIBLE_DATA_MODELS:
        if version < CURRENT_DATA_MODEL:
            if is_config_document(doc):
                migrate_config_document_to_v3(doc)
            stamp_data_model(doc)
            return CURRENT_DATA_MODEL
        if is_config_document(doc):
            # Already tagged 3 but may still carry path keys from partial packs.
            migrate_config_document_to_v3(doc)
        return version
    converter = _CONVERTERS.get(version)
    if converter is not None:
        converter(doc)
        stamp_data_model(doc)
        return CURRENT_DATA_MODEL
    raise DataModelError(
        f"{label}: earnie_data_model={version} ist nicht kompatibel "
        f"(aktuell {CURRENT_DATA_MODEL}, unterstützte Versionen: "
        f"{sorted(COMPATIBLE_DATA_MODELS)})."
    )
