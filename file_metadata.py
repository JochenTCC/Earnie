"""
file_metadata.py – Gemeinsame Metadaten für persistierte JSON-Dateien (Phase 1).

schema_version: Dateiformat (nur bei Strukturänderungen erhöhen)
written_by_app_version: App-Release, das die Datei geschrieben hat
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from version import __version__

RUN_STATE_SCHEMA = 1
CONS_DATA_META_SCHEMA = 1
CONS_DATA_PENDING_SCHEMA = 1
CONSUMER_STATE_SCHEMA = 1
PV_COUNTER_STATE_SCHEMA = 1
BACKTESTING_LOG_SCHEMA = 1

METADATA_KEYS = frozenset(
    {
        "schema_version",
        "version",
        "written_at",
        "written_by_app_version",
        "generated_at",
    }
)


def stamp_payload(payload: dict[str, Any], *, schema_version: int) -> dict[str, Any]:
    """Metadaten setzen; bestehende Metadaten im Payload werden ersetzt."""
    clean = strip_metadata(payload)
    return {
        "schema_version": schema_version,
        "written_at": datetime.now().isoformat(timespec="seconds"),
        "written_by_app_version": __version__,
        **clean,
    }


def strip_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Entfernt bekannte Metadaten-Keys aus einem JSON-Objekt."""
    return {key: value for key, value in raw.items() if key not in METADATA_KEYS}


def read_schema_version(raw: dict[str, Any], *, default: int = 0) -> int:
    """
    Liest die Schema-Version; akzeptiert legacy-Feld 'version'.
    Fehlt beides, wird default zurückgegeben (0 = unversioniert/legacy).
    """
    for key in ("schema_version", "version"):
        if key not in raw:
            continue
        try:
            return int(raw[key])
        except (TypeError, ValueError):
            return default
    return default
