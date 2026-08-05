"""Earnie config data-model versioning for save/load packs."""
from __future__ import annotations

from typing import Any

CURRENT_DATA_MODEL = 3
COMPATIBLE_DATA_MODELS: frozenset[int] = frozenset({3})

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
    return "live_scenario_id" in doc


def reject_legacy_config_structure(doc: dict[str, Any], *, label: str) -> None:
    """Reject pre-v3 config keys (no soft rename/strip)."""
    if _LEGACY_SIM_BLOCK in doc:
        raise DataModelError(
            f"{label}: '{_LEGACY_SIM_BLOCK}' ist nicht mehr unterstützt — "
            f"bitte '{_SIM_BLOCK}' verwenden (earnie_data_model={CURRENT_DATA_MODEL})."
        )
    block = doc.get(_SIM_BLOCK)
    if isinstance(block, dict):
        for key in _REMOVED_PATH_KEYS:
            if key in block:
                raise DataModelError(
                    f"{label}: '{_SIM_BLOCK}.{key}' ist entfernt — "
                    f"bitte aus der Konfiguration löschen "
                    f"(earnie_data_model={CURRENT_DATA_MODEL})."
                )


def ensure_compatible(doc: dict[str, Any], *, label: str) -> int:
    """
    Validate a document against the current data-model version.

    Missing tag or versions other than 3 raise ``DataModelError``.
    Config documents are also checked for removed structural keys.
    """
    version = read_data_model(doc)
    if version is None:
        raise DataModelError(
            f"{label}: earnie_data_model fehlt "
            f"(erforderlich: {CURRENT_DATA_MODEL})."
        )
    if version not in COMPATIBLE_DATA_MODELS:
        raise DataModelError(
            f"{label}: earnie_data_model={version} ist nicht kompatibel "
            f"(aktuell {CURRENT_DATA_MODEL}, unterstützte Versionen: "
            f"{sorted(COMPATIBLE_DATA_MODELS)})."
        )
    if is_config_document(doc):
        reject_legacy_config_structure(doc, label=label)
    return version
