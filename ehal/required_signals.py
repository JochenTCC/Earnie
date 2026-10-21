"""Required EHAL signal kinds per component type and control level (Binding P5a).

Activation = key present in ``ehal_bindings`` (value may be empty). This module
only lists *kinds* / qualified binding keys; it does not touch disk.

Plant bare ``sens_pv_production_active`` is retired: live PV is mandatory as
``inv.{id}.sens_inv_power_pv`` when the inverter has attached PV systems.
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
# Plant PV is derived from inv.*.sens_inv_power_pv — not a plant binding.
PLANT_REQUIRED_KINDS: tuple[str, ...] = (
    "sens_grid_power_active",
)

_BATTERY_TELEMETRY: tuple[str, ...] = ("sens_ess_soc",)
# Plant ``sens_ess_power`` is the sum of these per grid-tied house battery
# (``integrations.plant_balance``) — required there, optional elsewhere.
_BATTERY_GRID_TIED_POWER: tuple[str, ...] = ("sens_ess_power",)
_BATTERY_LIMITS: tuple[str, ...] = (
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
)
_BATTERY_FORCE: tuple[str, ...] = ("set_ess_active_power",)

_INVERTER_LIMIT: tuple[str, ...] = ("set_inv_ac_power_limit",)
_INVERTER_PV_TELEMETRY: tuple[str, ...] = ("sens_inv_power_pv",)
_EVCS_CURRENT: tuple[str, ...] = ("set_evcs_max_current",)

PLANT_PV_BINDING_KIND = "sens_pv_production_active"
PV_SYSTEM_PRODUCTION_KIND = "sens_pv_production_active"


def inverter_has_attached_pv(
    inverter_id: str,
    pv_systems: list[Any] | tuple[Any, ...] | None,
) -> bool:
    """True when at least one PV system references ``inverter_id``."""
    iid = str(inverter_id or "").strip()
    if not iid:
        return False
    for pv in pv_systems or []:
        if not isinstance(pv, dict):
            continue
        if str(pv.get("inverter_id") or "").strip() == iid:
            return True
    return False


def grid_tied_house_batteries(
    batteries: list[Any] | tuple[Any, ...] | None,
    inverters: list[Any] | tuple[Any, ...] | None,
) -> list[dict]:
    """House batteries that participate in the house AC balance (grid-tied bus)."""
    from house_config.powerstation import BATTERY_TYPE_HOUSE
    from optimizer.milp_inverter import filter_house_balance_batteries

    house = [
        b
        for b in batteries or []
        if isinstance(b, dict)
        and str(b.get("type") or BATTERY_TYPE_HOUSE).strip().lower() == BATTERY_TYPE_HOUSE
    ]
    return filter_house_balance_batteries(
        house, [i for i in inverters or [] if isinstance(i, dict)]
    )


def grid_tied_house_battery_ids(
    batteries: list[Any] | tuple[Any, ...] | None,
    inverters: list[Any] | tuple[Any, ...] | None,
) -> frozenset[str]:
    """Ids of grid-tied house batteries (plant ESS power is the sum of their power)."""
    return frozenset(
        str(b.get("id") or "").strip()
        for b in grid_tied_house_batteries(batteries, inverters)
        if str(b.get("id") or "").strip()
    )


def required_kinds_for_battery(
    control: str | None,
    *,
    grid_tied_house: bool = False,
) -> tuple[str, ...]:
    """ESS kinds required for the given ``batteries[].control`` level."""
    level = control_from_battery_params({"control": control})
    kinds = list(_BATTERY_TELEMETRY)
    if grid_tied_house:
        kinds.extend(_BATTERY_GRID_TIED_POWER)
    if level in (BATTERY_CONTROL_LIMITS_ONLY, BATTERY_CONTROL_FULL):
        kinds.extend(_BATTERY_LIMITS)
    if level == BATTERY_CONTROL_FULL:
        kinds.extend(_BATTERY_FORCE)
    if level == BATTERY_CONTROL_READ_ONLY:
        return tuple(kinds)
    return tuple(kinds)


def required_kinds_for_inverter(
    control: str | None,
    *,
    has_attached_pv: bool = False,
) -> tuple[str, ...]:
    """Inverter kinds required for ``inverters[].control`` and PV attachment."""
    level = str(control or DEFAULT_INVERTER_CONTROL).strip().lower()
    kinds: list[str] = []
    if has_attached_pv:
        kinds.extend(_INVERTER_PV_TELEMETRY)
    if level in ("full", "limits_only"):
        kinds.extend(_INVERTER_LIMIT)
    return tuple(kinds)


def required_kinds_for_pv_system() -> tuple[str, ...]:
    """Per-string PV production is optional — no required kinds."""
    return ()


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
    has_attached_pv: bool = False,
    grid_tied_house: bool = False,
) -> tuple[str, ...]:
    """Required ``ehal_bindings`` keys for one component instance."""
    if component_kind == "plant":
        kinds = required_kinds_for_plant()
    elif component_kind == "battery":
        kinds = required_kinds_for_battery(control, grid_tied_house=grid_tied_house)
    elif component_kind == "inverter":
        kinds = required_kinds_for_inverter(control, has_attached_pv=has_attached_pv)
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


def strip_empty_pv_production_keys(
    bindings: dict[str, Any] | None,
    *,
    pv_system_id: str,
) -> dict[str, Any]:
    """Drop empty unmapped ``pv.{id}.sens_pv_production_active`` leftovers."""
    out = dict(bindings) if isinstance(bindings, dict) else {}
    key = pv_field(str(pv_system_id or "").strip(), PV_SYSTEM_PRODUCTION_KIND)
    if key in out and not str(out.get(key) or "").strip():
        out.pop(key, None)
    return out


def strip_plant_pv_binding(bindings: dict[str, Any] | None) -> dict[str, Any]:
    """Remove retired plant ``sens_pv_production_active`` binding key."""
    out = dict(bindings) if isinstance(bindings, dict) else {}
    out.pop(PLANT_PV_BINDING_KIND, None)
    return out
