"""Catalog of EHAL signals for configured components (Binding P5b).

Role fields define what Earnie *can* use; ``ehal.required_signals`` marks
required kinds; activation = key present in ``ehal_bindings``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ehal.profiles import load_device_role
from ehal.push_signals import (
    pilot_id,
    title_from_qualified_id,
    vi_title_from_qualified_id,
)
from ehal.qualified_ids import field_kind, is_digital_id
from ehal.required_signals import (
    ComponentKind,
    binding_key_for_kind,
    required_binding_keys,
)
from house_config.battery_control import control_from_battery_params
from house_config.inverter import DEFAULT_INVERTER_CONTROL

Direction = Literal["read", "write"]


def _is_read(field: str) -> bool:
    return field_kind(field).startswith(("sens_", "get_"))


def _is_write(field: str) -> bool:
    return field_kind(field).startswith("set_")


def _group_for(entity_kind: str, entity_id: str) -> str:
    if entity_kind == "plant":
        return "Plant"
    if entity_kind == "battery":
        return f"Batterie_{entity_id}"
    if entity_kind == "inverter":
        return f"Wechselrichter_{entity_id}"
    if entity_kind == "pv_system":
        return f"PV_{entity_id}"
    if entity_id in ("pool_swimspa", "pool_filter"):
        return "Pool"
    if entity_id == "waermepumpe":
        return "Waermepumpe"
    if entity_id == "e_auto":
        return "EV"
    return "Verbraucher"


@dataclass(frozen=True)
class CatalogEntry:
    """One role-derived signal for a configured component instance."""

    component_kind: ComponentKind
    entity_id: str
    consumer_type: str
    binding_key: str
    ehal_id: str
    group: str
    direction: Direction
    digital: bool
    is_required: bool
    is_activated: bool


def _role_kinds(role_id: str) -> tuple[str, ...]:
    """Field kinds from a role template (skip capabilities / empty)."""
    role = load_device_role(role_id)
    kinds: list[str] = []
    seen: set[str] = set()
    for item in role.get("ehal_fields") or []:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "capability":
            continue
        raw = str(item.get("field") or "").strip()
        if not raw:
            continue
        kind = field_kind(raw.replace("{hk_id}", "x"))
        if not kind or kind.startswith("supports_") or kind in seen:
            continue
        if not (kind.startswith(("sens_", "get_", "set_"))):
            continue
        seen.add(kind)
        kinds.append(kind)
    return tuple(kinds)


def _bindings_of(entity: dict[str, Any] | None) -> dict[str, Any]:
    raw = (entity or {}).get("ehal_bindings") if isinstance(entity, dict) else None
    return raw if isinstance(raw, dict) else {}


def _key_activated(bindings: dict[str, Any], binding_key: str, entity_id: str) -> bool:
    if binding_key in bindings:
        return True
    kind = field_kind(binding_key)
    if not kind or not entity_id:
        return False
    # Legacy flex spelling for consumers (storage may still use flex.{slug}.*).
    from ehal.flex_fields import flex_ehal_slug

    slug = flex_ehal_slug(entity_id)
    return bool(slug) and f"flex.{slug}.{kind}" in bindings


def _entry(
    *,
    component_kind: ComponentKind,
    entity_id: str,
    kind: str,
    consumer_type: str,
    bindings: dict[str, Any],
    required: set[str],
) -> CatalogEntry | None:
    try:
        binding_key = binding_key_for_kind(
            component_kind=component_kind,
            entity_id=entity_id,
            kind=kind,
            consumer_type=consumer_type,
        )
    except ValueError:
        return None
    if _is_read(binding_key):
        direction: Direction = "read"
    elif _is_write(binding_key):
        direction = "write"
    else:
        return None
    ehal_id = pilot_id(component_kind, entity_id, binding_key, consumer_type)
    if not ehal_id:
        return None
    return CatalogEntry(
        component_kind=component_kind,
        entity_id=entity_id,
        consumer_type=consumer_type,
        binding_key=binding_key,
        ehal_id=ehal_id,
        group=_group_for(component_kind, entity_id),
        direction=direction,
        digital=is_digital_id(ehal_id),
        is_required=binding_key in required,
        is_activated=_key_activated(bindings, binding_key, entity_id),
    )


def _plant_kinds() -> tuple[str, ...]:
    # Plant wire: grid role only (plant PV retired; PV lives on inv.*/pv.*).
    return tuple(_role_kinds("grid"))


def _consumer_role_id(consumer_type: str) -> str:
    ctype = str(consumer_type or "").strip().lower()
    if ctype == "ev":
        return "evcs"
    if ctype == "thermal_annual":
        return "heatpump"
    return "consumer"


def iter_catalog_entries(house: dict, components: dict) -> list[CatalogEntry]:
    """All role signals for configured plant / batteries / inverters / PV / consumers."""
    out: list[CatalogEntry] = []
    seen: set[str] = set()

    def _add(entry: CatalogEntry | None) -> None:
        if entry is None or entry.binding_key in seen:
            return
        seen.add(entry.binding_key)
        out.append(entry)

    plant = house.get("plant") if isinstance(house.get("plant"), dict) else {}
    plant_bindings = _bindings_of(plant)
    plant_required = set(required_binding_keys(component_kind="plant"))
    for kind in _plant_kinds():
        _add(
            _entry(
                component_kind="plant",
                entity_id="plant",
                kind=kind,
                consumer_type="",
                bindings=plant_bindings,
                required=plant_required,
            )
        )

    for battery in components.get("batteries") or []:
        if not isinstance(battery, dict):
            continue
        bid = str(battery.get("id") or "").strip()
        if not bid:
            continue
        control = control_from_battery_params(battery)
        required = set(
            required_binding_keys(
                component_kind="battery", entity_id=bid, control=control
            )
        )
        bindings = _bindings_of(battery)
        for kind in _role_kinds("ess"):
            _add(
                _entry(
                    component_kind="battery",
                    entity_id=bid,
                    kind=kind,
                    consumer_type="",
                    bindings=bindings,
                    required=required,
                )
            )

    pv_systems = list(components.get("pv_systems") or [])
    from ehal.required_signals import inverter_has_attached_pv

    for inverter in components.get("inverters") or []:
        if not isinstance(inverter, dict):
            continue
        iid = str(inverter.get("id") or "").strip()
        if not iid:
            continue
        control = str(inverter.get("control") or DEFAULT_INVERTER_CONTROL).strip()
        required = set(
            required_binding_keys(
                component_kind="inverter",
                entity_id=iid,
                control=control,
                has_attached_pv=inverter_has_attached_pv(iid, pv_systems),
            )
        )
        bindings = _bindings_of(inverter)
        for kind in _role_kinds("inverter"):
            _add(
                _entry(
                    component_kind="inverter",
                    entity_id=iid,
                    kind=kind,
                    consumer_type="",
                    bindings=bindings,
                    required=required,
                )
            )

    for pv in components.get("pv_systems") or []:
        if not isinstance(pv, dict):
            continue
        pid = str(pv.get("id") or "").strip()
        if not pid:
            continue
        required = set(
            required_binding_keys(component_kind="pv_system", entity_id=pid)
        )
        bindings = _bindings_of(pv)
        for kind in _role_kinds("pv"):
            _add(
                _entry(
                    component_kind="pv_system",
                    entity_id=pid,
                    kind=kind,
                    consumer_type="",
                    bindings=bindings,
                    required=required,
                )
            )

    profiles = house.get("profiles") or {}
    profile_iter = (
        profiles.values() if isinstance(profiles, dict) else profiles
    )
    for profile in profile_iter:
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict):
                continue
            cid = str(consumer.get("id") or "").strip()
            if not cid:
                continue
            ctype = str(consumer.get("type") or "").strip()
            required = set(
                required_binding_keys(
                    component_kind="consumer",
                    entity_id=cid,
                    consumer_type=ctype,
                )
            )
            bindings = _bindings_of(consumer)
            for kind in _role_kinds(_consumer_role_id(ctype)):
                _add(
                    _entry(
                        component_kind="consumer",
                        entity_id=cid,
                        kind=kind,
                        consumer_type=ctype,
                        bindings=bindings,
                        required=required,
                    )
                )

    return out


def set_binding_activation(
    house: dict,
    components: dict,
    *,
    component_kind: ComponentKind,
    entity_id: str,
    binding_key: str,
    activated: bool,
    consumer_type: str = "",
    is_required: bool = False,
) -> tuple[dict, dict]:
    """Add or remove a binding key. Required keys cannot be deactivated."""
    if is_required and not activated:
        raise ValueError(f"required signal cannot be deactivated: {binding_key}")
    key = str(binding_key or "").strip()
    if not key:
        raise ValueError("binding_key must be non-empty")

    house_out = dict(house) if isinstance(house, dict) else {}
    comp_out = dict(components) if isinstance(components, dict) else {}

    if component_kind == "plant":
        plant = dict(house_out.get("plant") or {})
        bindings = dict(plant.get("ehal_bindings") or {})
        if activated:
            bindings.setdefault(key, "")
        else:
            bindings.pop(key, None)
        plant["ehal_bindings"] = bindings
        house_out["plant"] = plant
        return house_out, comp_out

    if component_kind == "consumer":
        profiles = house_out.get("profiles")
        if isinstance(profiles, dict):
            new_profiles: dict[str, Any] = {}
            for pname, profile in profiles.items():
                if not isinstance(profile, dict):
                    new_profiles[pname] = profile
                    continue
                consumers = []
                for consumer in profile.get("consumers") or []:
                    if not isinstance(consumer, dict):
                        consumers.append(consumer)
                        continue
                    if str(consumer.get("id") or "").strip() != entity_id:
                        consumers.append(consumer)
                        continue
                    c = dict(consumer)
                    bindings = dict(c.get("ehal_bindings") or {})
                    if activated:
                        bindings.setdefault(key, "")
                    else:
                        bindings.pop(key, None)
                        # Drop legacy flex peer of the same kind.
                        kind = field_kind(key)
                        flex = f"flex.{entity_id}.{kind}"
                        bindings.pop(flex, None)
                    c["ehal_bindings"] = bindings
                    consumers.append(c)
                new_profiles[pname] = {**profile, "consumers": consumers}
            house_out["profiles"] = new_profiles
        return house_out, comp_out

    list_key = {
        "battery": "batteries",
        "inverter": "inverters",
        "pv_system": "pv_systems",
    }.get(component_kind)
    if not list_key:
        raise ValueError(f"unsupported component_kind {component_kind!r}")
    items = []
    for item in comp_out.get(list_key) or []:
        if not isinstance(item, dict):
            items.append(item)
            continue
        if str(item.get("id") or "").strip() != entity_id:
            items.append(item)
            continue
        row = dict(item)
        bindings = dict(row.get("ehal_bindings") or {})
        if activated:
            bindings.setdefault(key, "")
        else:
            bindings.pop(key, None)
        row["ehal_bindings"] = bindings
        items.append(row)
    comp_out[list_key] = items
    _ = consumer_type
    return house_out, comp_out


def catalog_to_signals(
    entries: list[CatalogEntry],
    *,
    activated_only: bool,
) -> tuple[list, list]:
    """Build (read, write) ``Signal`` lists for VO/VI export from catalog."""
    from ehal.push_signals import Signal

    reads: list[Signal] = []
    writes: list[Signal] = []
    used_titles: set[str] = set()
    for entry in entries:
        if activated_only and not entry.is_activated:
            continue
        title_fn = (
            title_from_qualified_id
            if entry.direction == "read"
            else vi_title_from_qualified_id
        )
        base = title_fn(entry.ehal_id)
        title = base
        suffix = 2
        while title in used_titles:
            title, suffix = f"{base}_{suffix}", suffix + 1
        used_titles.add(title)
        sig = Signal(
            group=entry.group,
            ehal_id=entry.ehal_id,
            old_name=entry.ehal_id,
            title=title,
            digital=entry.digital,
        )
        if entry.direction == "read":
            reads.append(sig)
        else:
            writes.append(sig)
    return reads, writes
