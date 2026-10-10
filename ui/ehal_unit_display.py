"""EHAL-Com display helpers: hub/EHAL units and raw↔converted value pairs.

Units and factors come only from ``ehal.field_registry`` (role JSON) and
``integrations.ha_units`` — never hard-coded per field in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ehal.field_registry import (
    apply_loxone_read,
    apply_loxone_write,
    apply_openems_read,
    apply_openems_write,
    loxone_spec,
    openems_spec,
)
from ehal.qualified_ids import field_kind
from integrations.ha_units import QUANTITY_BASE_UNIT, field_quantity, from_ehal

Backend = Literal["loxone", "ha", "openems"]
ValueSpace = Literal["hub", "ehal"]

_DASH = "—"


@dataclass(frozen=True)
class FieldUnits:
    """Hub and EHAL unit labels for one field (None = unknown / no conversion)."""

    hub_unit: str | None
    ehal_unit: str | None


def units_for_field(
    ehal_id: str,
    backend: Backend,
    *,
    hub_unit_hint: str | None = None,
) -> FieldUnits:
    """Resolve hub/EHAL units for a qualified or bare EHAL ID."""
    kind = field_kind(ehal_id)
    if not kind:
        return FieldUnits(None, None)
    if backend == "loxone":
        spec = loxone_spec(kind)
        if spec is None:
            return FieldUnits(None, None)
        return FieldUnits(spec.unit, spec.ehal_unit)
    if backend == "openems":
        spec = openems_spec(kind)
        if spec is None:
            return FieldUnits(None, None)
        return FieldUnits(spec.unit, spec.ehal_unit)
    # HA: EHAL base from quantity map; hub unit only when entity unit is known.
    qty = field_quantity(kind)
    ehal_u = QUANTITY_BASE_UNIT.get(qty) if qty else None
    hub = str(hub_unit_hint).strip() if hub_unit_hint else None
    return FieldUnits(hub or None, ehal_u)


def format_value_with_unit(value: Any, unit: str | None) -> str:
    """Format a numeric/string value with an optional unit suffix."""
    if value is None:
        return _DASH
    text = str(value).strip()
    if not text:
        return _DASH
    if unit is None or not str(unit).strip():
        return text
    # Already has the unit suffix (e.g. ready-by display strings).
    if text.endswith(str(unit).strip()):
        return text
    try:
        num = float(text.replace(",", "."))
        text = f"{num:g}"
    except (TypeError, ValueError):
        pass
    return f"{text} {unit}".strip()


def _parse_float(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == _DASH:
        return None
    # Strip a trailing unit token if present (e.g. "2.5 kW").
    parts = text.split()
    candidate = parts[0].replace(",", ".") if parts else text
    try:
        return float(candidate)
    except (TypeError, ValueError):
        return None


def live_read_pair(
    ehal_id: str,
    backend: Backend,
    value: Any,
    *,
    value_space: ValueSpace,
    hub_unit_hint: str | None = None,
) -> tuple[str, str]:
    """Return ``(wert_hub_display, wert_ehal_display)`` for Live-Lesen.

    Fill only when a registry / ``ha_units`` path exists; otherwise ``—``.
    Non-numeric display strings stay on the side matching ``value_space``.
    """
    units = units_for_field(ehal_id, backend, hub_unit_hint=hub_unit_hint)
    kind = field_kind(ehal_id)
    num = _parse_float(value)
    if num is None:
        if value is None or str(value).strip() == "":
            return _DASH, _DASH
        text = str(value).strip()
        if value_space == "hub":
            return format_value_with_unit(text, units.hub_unit), _DASH
        return _DASH, format_value_with_unit(text, units.ehal_unit)

    if backend == "loxone":
        return _loxone_read_pair(kind, num, value_space, units)
    if backend == "openems":
        return _openems_read_pair(kind, num, value_space, units)
    return _ha_read_pair(kind, num, value_space, units, hub_unit_hint)


def live_write_pair(
    ehal_id: str,
    backend: Backend,
    value: Any,
    *,
    value_space: ValueSpace,
    hub_unit_hint: str | None = None,
) -> tuple[str, str]:
    """Return ``(wert_ehal_display, wert_hub_display)`` for Live-Schreiben."""
    units = units_for_field(ehal_id, backend, hub_unit_hint=hub_unit_hint)
    kind = field_kind(ehal_id)
    num = _parse_float(value)
    if num is None:
        if value is None or str(value).strip() == "":
            return _DASH, _DASH
        text = str(value).strip()
        if value_space == "ehal":
            return format_value_with_unit(text, units.ehal_unit), _DASH
        return _DASH, format_value_with_unit(text, units.hub_unit)

    if backend == "loxone":
        return _loxone_write_pair(kind, num, value_space, units)
    if backend == "openems":
        return _openems_write_pair(kind, num, value_space, units)
    return _ha_write_pair(kind, num, value_space, units, hub_unit_hint)


def _loxone_read_pair(
    kind: str, num: float, value_space: ValueSpace, units: FieldUnits
) -> tuple[str, str]:
    spec = loxone_spec(kind)
    if spec is None:
        text = format_value_with_unit(num, None)
        if value_space == "hub":
            return text, _DASH
        return _DASH, text
    if value_space == "hub":
        hub = format_value_with_unit(num, units.hub_unit)
        ehal_val = apply_loxone_read(num, spec)
        ehal = (
            format_value_with_unit(ehal_val, units.ehal_unit)
            if ehal_val is not None
            else _DASH
        )
        return hub, ehal
    ehal = format_value_with_unit(num, units.ehal_unit)
    hub = format_value_with_unit(apply_loxone_write(num, spec), units.hub_unit)
    return hub, ehal


def _loxone_write_pair(
    kind: str, num: float, value_space: ValueSpace, units: FieldUnits
) -> tuple[str, str]:
    """``(ehal_display, hub_display)`` — Loxone loud traces store hub units."""
    spec = loxone_spec(kind)
    if spec is None:
        text = format_value_with_unit(num, None)
        if value_space == "ehal":
            return text, _DASH
        return _DASH, text
    if value_space == "hub":
        hub = format_value_with_unit(num, units.hub_unit)
        ehal_val = apply_loxone_read(num, spec)
        ehal = (
            format_value_with_unit(ehal_val, units.ehal_unit)
            if ehal_val is not None
            else _DASH
        )
        return ehal, hub
    ehal = format_value_with_unit(num, units.ehal_unit)
    hub = format_value_with_unit(apply_loxone_write(num, spec), units.hub_unit)
    return ehal, hub


def _openems_read_pair(
    kind: str, num: float, value_space: ValueSpace, units: FieldUnits
) -> tuple[str, str]:
    spec = openems_spec(kind)
    if spec is None:
        text = format_value_with_unit(num, units.ehal_unit)
        if value_space == "ehal":
            return _DASH, text
        return text, _DASH
    if value_space == "ehal":
        ehal = format_value_with_unit(num, units.ehal_unit)
        hub = format_value_with_unit(apply_openems_write(num, spec), units.hub_unit)
        return hub, ehal
    hub = format_value_with_unit(num, units.hub_unit)
    ehal = format_value_with_unit(apply_openems_read(num, spec), units.ehal_unit)
    return hub, ehal


def _openems_write_pair(
    kind: str, num: float, value_space: ValueSpace, units: FieldUnits
) -> tuple[str, str]:
    spec = openems_spec(kind)
    if spec is None:
        text = format_value_with_unit(num, units.ehal_unit)
        if value_space == "ehal":
            return text, _DASH
        return _DASH, text
    if value_space == "ehal":
        ehal = format_value_with_unit(num, units.ehal_unit)
        hub = format_value_with_unit(apply_openems_write(num, spec), units.hub_unit)
        return ehal, hub
    hub = format_value_with_unit(num, units.hub_unit)
    ehal = format_value_with_unit(apply_openems_read(num, spec), units.ehal_unit)
    return ehal, hub


def _ha_read_pair(
    kind: str,
    num: float,
    value_space: ValueSpace,
    units: FieldUnits,
    hub_unit_hint: str | None,
) -> tuple[str, str]:
    ehal = format_value_with_unit(num, units.ehal_unit) if value_space == "ehal" else _DASH
    hub = _DASH
    if hub_unit_hint and units.ehal_unit:
        try:
            if value_space == "ehal":
                hub_val = from_ehal(kind, num, hub_unit_hint)
                hub = format_value_with_unit(hub_val, units.hub_unit)
                ehal = format_value_with_unit(num, units.ehal_unit)
            else:
                from integrations.ha_units import to_ehal

                hub = format_value_with_unit(num, units.hub_unit)
                ehal = format_value_with_unit(
                    to_ehal(kind, num, hub_unit_hint), units.ehal_unit
                )
        except Exception:  # noqa: BLE001 — mismatch / free field → dash
            if value_space == "ehal":
                ehal = format_value_with_unit(num, units.ehal_unit)
            else:
                hub = format_value_with_unit(num, units.hub_unit)
    elif value_space == "ehal":
        ehal = format_value_with_unit(num, units.ehal_unit)
    else:
        hub = format_value_with_unit(num, units.hub_unit)
    return hub, ehal


def _ha_write_pair(
    kind: str,
    num: float,
    value_space: ValueSpace,
    units: FieldUnits,
    hub_unit_hint: str | None,
) -> tuple[str, str]:
    if value_space == "ehal":
        ehal = format_value_with_unit(num, units.ehal_unit)
        hub = _DASH
        if hub_unit_hint:
            try:
                hub = format_value_with_unit(
                    from_ehal(kind, num, hub_unit_hint), units.hub_unit or hub_unit_hint
                )
            except Exception:  # noqa: BLE001
                hub = _DASH
        return ehal, hub
    hub = format_value_with_unit(num, units.hub_unit or hub_unit_hint)
    ehal = _DASH
    if hub_unit_hint:
        try:
            from integrations.ha_units import to_ehal

            ehal = format_value_with_unit(
                to_ehal(kind, num, hub_unit_hint), units.ehal_unit
            )
        except Exception:  # noqa: BLE001
            ehal = _DASH
    return ehal, hub
