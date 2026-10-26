"""Earnie config data-model versioning for save/load packs."""
from __future__ import annotations

from typing import Any

CURRENT_DATA_MODEL = 5
COMPATIBLE_DATA_MODELS: frozenset[int] = frozenset({5})
# 3 and 4 load only through the migration registry (wizard / scripts.migrate_config)
MIGRATABLE_DATA_MODELS: frozenset[int] = frozenset({3, 4})

DATA_MODEL_KEY = "earnie_data_model"

# Tariff track (Edibert P2): own format version, owned by Edibert (``edibert.api``
# ``TARIFF_FORMAT`` / ``TARIFF_TRACK_FILES``; equality checked by tests). These files are
# never stamped with earnie_data_model; untagged ones are migrated by ``tf1.tariff_format``.
TARIFF_FORMAT_KEY = "tariff_format"
CURRENT_TARIFF_FORMAT = 1
TARIFF_TRACK_FILES: frozenset[str] = frozenset(
    {"tariffs.json", "user_tariffs.json", "grid_fees.json", "user_grid_fees.json"}
)
# Shipped tariff templates (share/config): same track, never stamped with earnie_data_model.
TARIFF_TRACK_TEMPLATES: frozenset[str] = frozenset({"tariffs.example.json", "tariffs.minimal.json"})

_LEGACY_SIM_BLOCK = "file_paths_battery_simulation"
_SIM_BLOCK = "scenario_explorer_conf"
_REMOVED_PATH_KEYS = ("path_consumption", "path_production")


class DataModelError(ValueError):
    """Raised when a document's data-model version is unsupported."""


_MIGRATE_HINT = (
    "Streamlit-Seite „Konfigurations-Migration“ oder "
    "python -m scripts.migrate_config --config-dir <config>"
)


def is_tariff_track_file(name: str) -> bool:
    """True for tariff-track files and their shipped templates (basename)."""
    return name in TARIFF_TRACK_FILES or name in TARIFF_TRACK_TEMPLATES


def ensure_tariff_format(doc: Any, *, label: str) -> None:
    """Tariff-track file must carry the current ``tariff_format`` (no untagged / dual read)."""
    if not isinstance(doc, dict):
        raise DataModelError(f"{label}: erwartet JSON-Objekt.")
    raw = doc.get(TARIFF_FORMAT_KEY)
    if raw is None:
        raise DataModelError(
            f"{label}: {TARIFF_FORMAT_KEY} fehlt (erforderlich: {CURRENT_TARIFF_FORMAT}) — "
            f"Konfiguration zuerst migrieren ({_MIGRATE_HINT})."
        )
    if isinstance(raw, bool) or raw != CURRENT_TARIFF_FORMAT:
        raise DataModelError(
            f"{label}: {TARIFF_FORMAT_KEY}={raw!r} wird nicht unterstützt "
            f"(aktuell {CURRENT_TARIFF_FORMAT})."
        )


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

    Missing tag or versions other than the current raise ``DataModelError``.
    Config documents are also checked for removed structural keys.
    """
    version = read_data_model(doc)
    _hint = _MIGRATE_HINT
    if version is None:
        raise DataModelError(
            f"{label}: earnie_data_model fehlt "
            f"(erforderlich: {CURRENT_DATA_MODEL}) — {_hint}."
        )
    if version in MIGRATABLE_DATA_MODELS:
        raise DataModelError(
            f"{label}: earnie_data_model={version} muss zuerst nach "
            f"{CURRENT_DATA_MODEL} migriert werden ({_hint})."
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
