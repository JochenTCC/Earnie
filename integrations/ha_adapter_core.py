"""Home Assistant adapter core: config, errors, constants and pure helpers.

Split out of ``integrations.ha_adapter`` (public names are re-exported there).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from integrations.ha_units import to_ehal

# Keep the historic logger name so log filters keep working after the split.
logger = logging.getLogger("integrations.ha_adapter")

# Boolean/enum invert for fields where HA ON/high does not match EHAL polarity.
# Modes: "ehal" (identity) or "invert" (flip 0↔1 / on↔off). Separate from numeric sign.
BOOLEAN_INVERT_FIELDS = frozenset({"set_ess_source_select"})
_NONNEG_TELEMETRY = frozenset(
    {
        "sens_evcs_active_power",
        "sens_power_consumers",
        "get_ess_max_charge_power",
        "get_ess_max_discharge_power",
        "sens_inv_power_pv",
    }
)


@dataclass
class _HaWriteOutcome:
    """Fehlfelder, Meldungen und Capability-Flips eines Setpoint-Schreibvorgangs."""

    failed: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    hub_status: str | None = None
    flip_ess: bool = False
    flip_evcs: bool = False
    skipped: list[str] = field(default_factory=list)
    # Never activated (not an incomplete mapping): nothing was written, no record.
    unconfigured: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HaConfig:
    base_url: str
    token: str
    adapter_id: str
    entities: dict[str, str] = field(default_factory=dict)
    sign: dict[str, str] = field(default_factory=dict)
    # Per-field boolean/enum polarity: "ehal" (default) or "invert" (0↔1).
    boolean_invert: dict[str, str] = field(default_factory=dict)
    timeout_sec: float = 10.0
    ha_ess_force: dict[str, Any] | None = None
    # Binding P5e: push-only; ``transport`` kept for call-site compatibility (ignored).
    transport: str = "push"
    push_read_qids: dict[str, str] = field(default_factory=dict)
    setpoint_qids: dict[str, str] = field(default_factory=dict)


def apply_boolean_invert(value: float | int | bool, mode: str | None) -> float:
    """Map EHAL 0/1 through optional invert for HA switch/binary polarity."""
    numeric = 1.0 if bool(float(value)) else 0.0
    if str(mode or "ehal").strip().lower() == "invert":
        return 0.0 if numeric >= 0.5 else 1.0
    return numeric


class HaHttpError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _utc_ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def apply_sign(value: float, mode: str | None) -> float:
    """Apply configured sign mode: ehal (noop) or negate."""
    if str(mode or "ehal").strip().lower() == "negate":
        return -float(value)
    return float(value)


def _parse_ha_number(state: str) -> float:
    text = str(state).strip().replace(",", ".")
    if text.lower() in ("", "unavailable", "unknown", "none"):
        raise ValueError(f"HA state is not numeric: {state!r}")
    return float(text)


def parse_ha_field_value(field_name: str, state: str, *, unit: str | None) -> float:
    """Parse HA state for an EHAL field; convert entity unit → EHAL base unit.

    Raises ``UnitMismatchError`` (a ``ValueError``) if the entity's unit belongs
    to another physical quantity (e.g. kWh bound to a power field).
    """
    return to_ehal(field_name, _parse_ha_number(state), unit)


def entity_domain(entity_id: str) -> str:
    return str(entity_id).split(".", 1)[0].strip().lower()


def _safe_json_or_text(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return getattr(response, "text", None)
