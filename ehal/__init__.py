"""EHAL — Earnie Hardware Access Layer (M1 wire types + schema validation).

No network I/O. No OpenEMS / Home Assistant / Loxone imports.
Canonical spec: docs/spec/ehal.md

Device-role / hardware-profile / Loxone recipe loaders: ``ehal.profiles`` (2.4.g).
"""

from ehal.models import (
    EHAL_SCHEMA_VERSION,
    EhalCapabilities,
    EhalSetpoint,
    EhalTelemetry,
    EhalWriteError,
)
from ehal.validate import (
    EhalValidationError,
    validate_capabilities,
    validate_setpoint,
    validate_telemetry,
    validate_write_error,
)

__all__ = [
    "EHAL_SCHEMA_VERSION",
    "EhalCapabilities",
    "EhalSetpoint",
    "EhalTelemetry",
    "EhalValidationError",
    "EhalWriteError",
    "validate_capabilities",
    "validate_setpoint",
    "validate_telemetry",
    "validate_write_error",
]
