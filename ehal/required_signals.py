"""Required EHAL signal kinds per component type and control level (Binding P5a).

Activation = key present in ``ehal_bindings`` (value may be empty). This module
only lists *kinds* / qualified binding keys; it does not touch disk.
"""
from __future__ import annotations

from typing import Any, Literal

from ehal.ess_fields import ess_field
from ehal.inverter_fields import inv_field
from ehal.pv_fields import pv_field
from ehal.qualified_ids import qualified_consumer_id
from house_config.battery_control import (
    BATTERY_CONTROL_FULL,
    BATTERY_CONTROL_LIMITS_ONLY,
    BATTERY_CONTROL_READ_ONLY,
    control_from_battery_params,
)
from house_config.inverter import DEFAULT_INVERTER_CONTROL

ComponentKind = Literal["plant", "battery", "inverter", "pv_system", "consumer"]

# Plant bare keys from telemetry (sens_ess_soc lives on the battery entity).
PLANT_REQUIRED_KINDS: tuple[str, ...] = (
    "sens_grid_power_active",
    "sens_pv_production_active",
)

_BATTERY_TELEMETRY: tuple[str, ...] = ("sens_ess_soc",)
_BATTERY_LIMITS: tuple[str, ...] = (
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
)
_BATTERY_FORCE: tuple[str, ...] = ("set_ess_active_power",)

_INVERTER_LIMIT: tuple[str, ...] = ("set_inv_ac_power_limit",)
_PV_TELEMETRY: tuple[str, ...] = ("sens_pv_production_active",)
_EVCS_CURRENT: tuple[str, ...] = ("set_evcs_max_current",)


def required_kinds_for_battery(control: str | None) -> tuple[str, ...]:
    """ESS kinds required for the given ``batteries[].control`` level."""
    level = control_from_battery_params({"control": control})
    kinds = list(_BATTERY_TELEMETRY)
    if level in (BATTERY_CONTROL_LIMITS_ONLY, BATTERY_CONTROL_FULL):
        kinds.extend(_BATTERY_LIMITS)
    if level == BATTERY_CONTROL_FULL:
        kinds.extend(_BATTERY_FORCE)
    if level == BATTERY_CONTROL_READ_ONLY:
        return tuple(kinds)
    return tuple(kinds)


def required_kinds_for_inverter(control: str | None) -> tuple[str, ...]:
    """Inverter kinds required for ``inverters[].control``."""
    level = str(control or DEFAULT_INVERTER_CONTROL).strip().lower()
    if level in ("full", "limits_only"):
        return _INVERTER_LIMIT
    return ()


def required_kinds_for_pv_system() -> tuple[str, ...]:
    return _PV_TELEMETRY


def required_kinds_for_plant() -> tuple[str, ...]:
    return PLANT_REQUIRED_KINDS


def required_kinds_for_consumer(consumer_type: str) -> tuple[str, ...]:
    """Consumer binding kinds (flat / flex spelling as stored in ``ehal_bindings``)."""
    ctype = str(consumer_type or "").strip().lower()
    if ctype == "ev":
        return _EVCS_CURRENT
    if ctype in ("flex", "thermal_annual", "thermal_rc", "pool", "pool_filter"):
        return ("set_enable",)
    return ()


def binding_key_for_kind(
    *,
    component_kind: ComponentKind,
    entity_id: str,
    kind: str,
    consumer_type: str = "",
) -> str:
    """Storage key for ``ehal_bindings`` (entity-scoped where the product uses it)."""
    kind_s = str(kind or "").strip()
    eid = str(entity_id or "").strip()
    if component_kind == "battery":
        if not eid:
            raise ValueError("battery required-signal key needs a non-empty id")
        return ess_field(eid, kind_s)
    if component_kind == "inverter":
        if not eid:
            raise ValueError("inverter required-signal key needs a non-empty id")
        return inv_field(eid, kind_s)
    if component_kind == "pv_system":
        if not eid:
            raise ValueError("pv_system required-signal key needs a non-empty id")
        return pv_field(eid, kind_s)
    if component_kind == "consumer":
        if not eid:
            raise ValueError("consumer required-signal key needs a non-empty id")
        return qualified_consumer_id(eid, consumer_type, kind_s)
    return kind_s


def required_binding_keys(
    *,
    component_kind: ComponentKind,
    entity_id: str = "",
    control: str | None = None,
    consumer_type: str = "",
) -> tuple[str, ...]:
    """Required ``ehal_bindings`` keys for one component instance."""
    if component_kind == "plant":
        kinds = required_kinds_for_plant()
    elif component_kind == "battery":
        kinds = required_kinds_for_battery(control)
    elif component_kind == "inverter":
        kinds = required_kinds_for_inverter(control)
    elif component_kind == "pv_system":
        kinds = required_kinds_for_pv_system()
    elif component_kind == "consumer":
        kinds = required_kinds_for_consumer(consumer_type)
    else:
        raise ValueError(f"unknown component_kind {component_kind!r}")
    return tuple(
        binding_key_for_kind(
            component_kind=component_kind,
            entity_id=entity_id,
            kind=kind,
            consumer_type=consumer_type,
        )
        for kind in kinds
    )


def activate_required_keys(
    bindings: dict[str, Any] | None,
    keys: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Return a copy of ``bindings`` with each key present (empty value if new)."""
    out = dict(bindings) if isinstance(bindings, dict) else {}
    for key in keys:
        name = str(key or "").strip()
        if not name:
            continue
        out.setdefault(name, "")
    return out


def strip_entity_keys(
    bindings: dict[str, Any] | None,
    *,
    prefix: str | None = None,
    keys: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Drop keys for a deleted entity (by exact set and/or qualified prefix)."""
    out = dict(bindings) if isinstance(bindings, dict) else {}
    drop = {str(k).strip() for k in (keys or ()) if str(k).strip()}
    pref = str(prefix or "").strip()
    if not drop and not pref:
        return out
    return {
        k: v
        for k, v in out.items()
        if str(k) not in drop and not (pref and str(k).startswith(pref))
    }


def missing_required_keys(
    bindings: dict[str, Any] | None,
    keys: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    present = set((bindings or {}).keys()) if isinstance(bindings, dict) else set()
    return tuple(k for k in keys if k not in present)
