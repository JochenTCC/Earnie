"""Earnie config data-model versioning for save/load packs."""
from __future__ import annotations

from typing import Any, Callable

CURRENT_DATA_MODEL = 1
COMPATIBLE_DATA_MODELS: frozenset[int] = frozenset({1})

# Future: map from source version → callable that mutates a document in place.
_CONVERTERS: dict[int, Callable[[dict[str, Any]], None]] = {}

DATA_MODEL_KEY = "earnie_data_model"


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


def ensure_compatible(doc: dict[str, Any], *, label: str) -> int:
    """
    Validate / convert a document to a compatible data-model version.

    Missing tag is treated as version 1 (legacy files before tagging).
    """
    version = read_data_model(doc)
    if version is None:
        version = 1
        doc[DATA_MODEL_KEY] = version
    if version in COMPATIBLE_DATA_MODELS:
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
