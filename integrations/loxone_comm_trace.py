"""Nachverfolgung von Loxone-Schreibvorgängen für Debug-UI und run_state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LoxoneWriteRecord:
    """Einzelner HTTP-Schreibvorgang an einen virtuellen Loxone-Eingang."""

    io_name: str
    value: float
    success: bool
    written_at: str  # ISO local, timespec="seconds"

    def to_dict(self) -> dict[str, Any]:
        return {
            "io_name": self.io_name,
            "value": self.value,
            "success": self.success,
            "written_at": self.written_at,
        }


def serialize_write_records(records: list[LoxoneWriteRecord]) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]
