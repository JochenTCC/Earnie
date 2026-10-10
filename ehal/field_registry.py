"""EHAL field registry: hub ↔ EHAL conversion from role JSON.

Loxone: optional ``loxone`` blocks (factor/sign = hub → EHAL). Reads use
``apply_loxone_read``; writes use ``apply_loxone_write`` (inverse after EHAL clamps).
OpenEMS: optional ``openems`` blocks (W-native polarity / clamps).

Mapping completeness stays on top-level ``required`` in role JSON. Loxone abort
vs omit is ``loxone.read_required``. Decision logic (derive consumers, plant
alias, Automatik omit) stays in the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ehal.profiles import list_device_roles, load_device_role


@dataclass(frozen=True)
class LoxoneConversionSpec:
    """Static Loxone ↔ EHAL conversion for one field kind.

    ``factor`` / ``sign`` always mean hub → EHAL (``ehal = hub * sign * factor``).
    Write applies the inverse after EHAL-space clamps.
    """

    field: str
    unit: str
    ehal_unit: str
    factor: float
    sign: float
    clamp_min: float | None
    clamp_max: float | None
    omit_if: str | None
    read_required: bool


@dataclass(frozen=True)
class OpenemsConversionSpec:
    """Static OpenEMS ↔ EHAL polarity / clamp (units already W)."""

    field: str
    unit: str
    ehal_unit: str
    factor: float
    sign: float
    clamp_min: float | None
    clamp_max: float | None


# Plant telemetry fields read by LoxoneAdapter.read_telemetry (order fixed).
PLANT_REQUIRED_READ_FIELDS: tuple[str, ...] = (
    "sens_ess_soc",
    "sens_pv_production_active",
    "sens_grid_power_active",
    "sens_ess_power",
)

PLANT_OPTIONAL_READ_FIELDS: tuple[str, ...] = (
    "get_grid_export_power_limit",
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_omit(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clamp_ehal(value: float, clamp_min: float | None, clamp_max: float | None) -> float:
    out = float(value)
    if clamp_min is not None:
        out = max(float(clamp_min), out)
    if clamp_max is not None:
        out = min(float(clamp_max), out)
    return out


@lru_cache(maxsize=1)
def _loxone_specs() -> dict[str, LoxoneConversionSpec]:
    out: dict[str, LoxoneConversionSpec] = {}
    for role_id in list_device_roles():
        doc = load_device_role(role_id)
        for entry in doc.get("ehal_fields") or []:
            if not isinstance(entry, dict):
                continue
            block = entry.get("loxone")
            if not isinstance(block, dict):
                continue
            field = str(entry.get("field") or "").strip()
            if not field:
                continue
            out[field] = LoxoneConversionSpec(
                field=field,
                unit=str(block["unit"]),
                ehal_unit=str(block["ehal_unit"]),
                factor=float(block["factor"]),
                sign=float(block["sign"]),
                clamp_min=_optional_float(block.get("clamp_min")),
                clamp_max=_optional_float(block.get("clamp_max")),
                omit_if=_optional_omit(block.get("omit_if")),
                read_required=bool(block.get("read_required", False)),
            )
    return out


@lru_cache(maxsize=1)
def _openems_specs() -> dict[str, OpenemsConversionSpec]:
    out: dict[str, OpenemsConversionSpec] = {}
    for role_id in list_device_roles():
        doc = load_device_role(role_id)
        for entry in doc.get("ehal_fields") or []:
            if not isinstance(entry, dict):
                continue
            block = entry.get("openems")
            if not isinstance(block, dict):
                continue
            field = str(entry.get("field") or "").strip()
            if not field:
                continue
            out[field] = OpenemsConversionSpec(
                field=field,
                unit=str(block.get("unit") or "W"),
                ehal_unit=str(block.get("ehal_unit") or "W"),
                factor=float(block.get("factor", 1)),
                sign=float(block["sign"]),
                clamp_min=_optional_float(block.get("clamp_min")),
                clamp_max=_optional_float(block.get("clamp_max")),
            )
    return out


def clear_loxone_spec_cache() -> None:
    """Test helper: drop cached role conversion maps."""
    _loxone_specs.cache_clear()
    _openems_specs.cache_clear()


def loxone_spec(field: str) -> LoxoneConversionSpec | None:
    """Return Loxone conversion for a bare EHAL field kind, or None."""
    kind = str(field or "").strip()
    if not kind:
        return None
    return _loxone_specs().get(kind)


def openems_spec(field: str) -> OpenemsConversionSpec | None:
    """Return OpenEMS conversion for a bare EHAL field kind, or None."""
    kind = str(field or "").strip()
    if not kind:
        return None
    return _openems_specs().get(kind)


def apply_loxone_read(raw: Any, spec: LoxoneConversionSpec) -> float | None:
    """Convert a raw Loxone numeric value to EHAL; None means omit the field."""
    try:
        value = None if raw is None else float(raw)
    except (TypeError, ValueError):
        return None
    if value is None:
        return None
    if spec.omit_if == "negative" and value < 0.0:
        return None
    out = float(value) * float(spec.sign) * float(spec.factor)
    return _clamp_ehal(out, spec.clamp_min, spec.clamp_max)


def apply_loxone_write(value_ehal: float, spec: LoxoneConversionSpec) -> float:
    """Convert an EHAL value to Loxone hub units (inverse of hub → EHAL).

    Applies ``clamp_min`` / ``clamp_max`` in EHAL space first. Ignores
    ``omit_if`` and ``read_required``.
    """
    scale = float(spec.sign) * float(spec.factor)
    if scale == 0.0:
        raise ValueError(f"loxone write factor/sign is zero for {spec.field}")
    ehal = _clamp_ehal(float(value_ehal), spec.clamp_min, spec.clamp_max)
    return ehal / scale


def apply_openems_read(raw: Any, spec: OpenemsConversionSpec) -> float:
    """Convert a raw OpenEMS numeric value to EHAL."""
    value = float(raw)
    out = value * float(spec.sign) * float(spec.factor)
    return _clamp_ehal(out, spec.clamp_min, spec.clamp_max)


def apply_openems_write(value_ehal: float, spec: OpenemsConversionSpec) -> float:
    """Convert an EHAL value to OpenEMS channel units (inverse of hub → EHAL)."""
    scale = float(spec.sign) * float(spec.factor)
    if scale == 0.0:
        raise ValueError(f"openems write factor/sign is zero for {spec.field}")
    ehal = _clamp_ehal(float(value_ehal), spec.clamp_min, spec.clamp_max)
    return ehal / scale


def require_loxone_write(field: str, value_ehal: float) -> float:
    """Look up setpoint ``loxone`` block and convert; raise if missing."""
    spec = loxone_spec(field)
    if spec is None:
        raise KeyError(f"no loxone write conversion for field {field!r}")
    return apply_loxone_write(value_ehal, spec)


def require_openems_write(field: str, value_ehal: float) -> float:
    """Look up setpoint ``openems`` block and convert; raise if missing."""
    spec = openems_spec(field)
    if spec is None:
        raise KeyError(f"no openems write conversion for field {field!r}")
    return apply_openems_write(value_ehal, spec)
