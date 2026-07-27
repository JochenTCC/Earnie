"""Load share/ehal JSON Schemas and validate EHAL documents."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from ehal.models import (
    EhalCapabilities,
    EhalSetpoint,
    EhalTelemetry,
    EhalWriteError,
)

_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "share" / "ehal"

_SCHEMA_FILES = {
    "telemetry": "telemetry.schema.json",
    "setpoint": "setpoint.schema.json",
    "capabilities": "capabilities.schema.json",
    "write_error": "write_error.schema.json",
}


class EhalValidationError(ValueError):
    """Raised when an EHAL document fails JSON Schema validation."""


def schema_dir() -> Path:
    """Return the directory containing share/ehal/*.schema.json."""
    return _SCHEMA_DIR


@lru_cache(maxsize=8)
def load_schema(kind: str) -> dict[str, Any]:
    """Load a named EHAL schema (telemetry|setpoint|capabilities|write_error)."""
    filename = _SCHEMA_FILES.get(kind)
    if filename is None:
        raise KeyError(f"Unknown EHAL schema kind: {kind!r}")
    path = _SCHEMA_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"EHAL schema not found: {path}")
    with path.open(encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise ValueError(f"EHAL schema must be an object: {path}")
    return doc


def _validate(kind: str, document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise EhalValidationError(
            f"EHAL {kind} document must be a JSON object, got {type(document).__name__}"
        )
    schema = load_schema(kind)
    try:
        jsonschema.validate(instance=document, schema=schema)
    except jsonschema.ValidationError as exc:
        raise EhalValidationError(
            f"EHAL {kind} failed schema validation: {exc.message}"
        ) from exc
    return document


def validate_telemetry(document: dict[str, Any]) -> EhalTelemetry:
    """Validate and return an EHAL telemetry document."""
    return _validate("telemetry", document)  # type: ignore[return-value]


def validate_setpoint(document: dict[str, Any]) -> EhalSetpoint:
    """Validate and return an EHAL setpoint document."""
    return _validate("setpoint", document)  # type: ignore[return-value]


def validate_capabilities(document: dict[str, Any]) -> EhalCapabilities:
    """Validate and return an EHAL capabilities document."""
    return _validate("capabilities", document)  # type: ignore[return-value]


def validate_write_error(document: dict[str, Any]) -> EhalWriteError:
    """Validate and return an EHAL write-error document."""
    return _validate("write_error", document)  # type: ignore[return-value]
