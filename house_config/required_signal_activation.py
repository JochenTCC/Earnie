"""Activate required EHAL binding keys on Hauskonfigurator save / migration (P5a)."""
from __future__ import annotations

from typing import Any

from ehal.required_signals import (
    activate_required_keys,
    grid_tied_house_battery_ids,
    inverter_has_attached_pv,
    missing_required_keys,
    required_binding_keys,
    strip_empty_pv_production_keys,
    strip_plant_pv_binding,
)
from house_config.battery_control import control_from_battery_params
from house_config.inverter import DEFAULT_INVERTER_CONTROL


def activate_plant_required(plant: dict[str, Any]) -> dict[str, Any]:
    """Return plant dict with required plant keys; strip retired plant PV binding."""
    out = dict(plant) if isinstance(plant, dict) else {}
    keys = required_binding_keys(component_kind="plant")
    bindings = activate_required_keys(out.get("ehal_bindings"), keys)
    out["ehal_bindings"] = strip_plant_pv_binding(bindings)
    return out


def activate_battery_required(
    battery: dict[str, Any],
    *,
    grid_tied_house: bool = False,
) -> dict[str, Any]:
    """``grid_tied_house``: battery is on the grid-tied bus → ``sens_ess_power`` required."""
    out = dict(battery) if isinstance(battery, dict) else {}
    bid = str(out.get("id") or "").strip()
    if not bid:
        return out
    control = control_from_battery_params(out)
    keys = required_binding_keys(
        component_kind="battery",
        entity_id=bid,
        control=control,
        grid_tied_house=grid_tied_house,
    )
    out["ehal_bindings"] = activate_required_keys(out.get("ehal_bindings"), keys)
    return out


def activate_inverter_required(
    inverter: dict[str, Any],
    *,
    pv_systems: list[Any] | tuple[Any, ...] | None = None,
) -> dict[str, Any]:
    out = dict(inverter) if isinstance(inverter, dict) else {}
    iid = str(out.get("id") or "").strip()
    if not iid:
        return out
    control = str(out.get("control") or DEFAULT_INVERTER_CONTROL).strip().lower()
    has_pv = inverter_has_attached_pv(iid, pv_systems)
    keys = required_binding_keys(
        component_kind="inverter",
        entity_id=iid,
        control=control,
        has_attached_pv=has_pv,
    )
    out["ehal_bindings"] = activate_required_keys(out.get("ehal_bindings"), keys)
    return out


def activate_pv_system_required(pv: dict[str, Any]) -> dict[str, Any]:
    """PV systems have no required kinds; strip empty optional production keys."""
    out = dict(pv) if isinstance(pv, dict) else {}
    pid = str(out.get("id") or "").strip()
    if not pid:
        return out
    out["ehal_bindings"] = strip_empty_pv_production_keys(
        out.get("ehal_bindings"), pv_system_id=pid
    )
    return out


def activate_consumer_required(consumer: dict[str, Any]) -> dict[str, Any]:
    out = dict(consumer) if isinstance(consumer, dict) else {}
    cid = str(out.get("id") or "").strip()
    if not cid:
        return out
    ctype = str(out.get("type") or "").strip()
    keys = required_binding_keys(
        component_kind="consumer", entity_id=cid, consumer_type=ctype
    )
    if not keys:
        return out
    out["ehal_bindings"] = activate_required_keys(out.get("ehal_bindings"), keys)
    return out


def activate_batteries_required(
    batteries: list[Any] | tuple[Any, ...] | None,
    inverters: list[Any] | tuple[Any, ...] | None,
) -> list[Any]:
    """Required keys on every battery; grid-tied house batteries also need ``sens_ess_power``.

    Call again after an inverter changes (``ac_connection``) — it decides which
    batteries are grid-tied.
    """
    grid_tied = grid_tied_house_battery_ids(batteries, inverters)
    return [
        activate_battery_required(
            b, grid_tied_house=str(b.get("id") or "").strip() in grid_tied
        )
        if isinstance(b, dict)
        else b
        for b in list(batteries or [])
    ]


def activate_required_in_components(components: dict[str, Any]) -> dict[str, Any]:
    """Activate required keys on all batteries / inverters / PV systems."""
    out = dict(components) if isinstance(components, dict) else {}
    pv_systems = list(out.get("pv_systems") or [])
    out["batteries"] = activate_batteries_required(
        out.get("batteries"), out.get("inverters")
    )
    out["inverters"] = [
        activate_inverter_required(i, pv_systems=pv_systems)
        if isinstance(i, dict)
        else i
        for i in list(out.get("inverters") or [])
    ]
    out["pv_systems"] = [
        activate_pv_system_required(p) if isinstance(p, dict) else p
        for p in pv_systems
    ]
    return out


def activate_required_in_house(house: dict[str, Any]) -> dict[str, Any]:
    """Activate required keys on plant and every consumer in every profile."""
    out = dict(house) if isinstance(house, dict) else {}
    plant = out.get("plant")
    if isinstance(plant, dict):
        out["plant"] = activate_plant_required(plant)
    profiles = out.get("profiles")
    if isinstance(profiles, dict):
        new_profiles: dict[str, Any] = {}
        for key, profile in profiles.items():
            if not isinstance(profile, dict):
                new_profiles[key] = profile
                continue
            consumers = [
                activate_consumer_required(c) if isinstance(c, dict) else c
                for c in list(profile.get("consumers") or [])
            ]
            new_profiles[key] = {**profile, "consumers": consumers}
        out["profiles"] = new_profiles
    elif isinstance(profiles, list):
        new_list = []
        for profile in profiles:
            if not isinstance(profile, dict):
                new_list.append(profile)
                continue
            consumers = [
                activate_consumer_required(c) if isinstance(c, dict) else c
                for c in list(profile.get("consumers") or [])
            ]
            new_list.append({**profile, "consumers": consumers})
        out["profiles"] = new_list
    return out


def pack_missing_required(
    house: dict[str, Any] | None,
    components: dict[str, Any] | None,
) -> bool:
    """True when any configured component still lacks a required activation key."""
    if isinstance(house, dict):
        plant = house.get("plant")
        if isinstance(plant, dict):
            keys = required_binding_keys(component_kind="plant")
            if missing_required_keys(plant.get("ehal_bindings"), keys):
                return True
            # Retired plant PV key still present → migration/activation needed.
            bindings = plant.get("ehal_bindings")
            if isinstance(bindings, dict) and "sens_pv_production_active" in bindings:
                return True
        profiles = house.get("profiles") or {}
        items = profiles.values() if isinstance(profiles, dict) else profiles
        for profile in items or []:
            if not isinstance(profile, dict):
                continue
            for consumer in profile.get("consumers") or []:
                if not isinstance(consumer, dict):
                    continue
                cid = str(consumer.get("id") or "").strip()
                ctype = str(consumer.get("type") or "").strip()
                if not cid:
                    continue
                keys = required_binding_keys(
                    component_kind="consumer",
                    entity_id=cid,
                    consumer_type=ctype,
                )
                if keys and missing_required_keys(consumer.get("ehal_bindings"), keys):
                    return True
    if isinstance(components, dict):
        pv_systems = list(components.get("pv_systems") or [])
        grid_tied = grid_tied_house_battery_ids(
            components.get("batteries"), components.get("inverters")
        )
        for battery in components.get("batteries") or []:
            if not isinstance(battery, dict):
                continue
            bid = str(battery.get("id") or "").strip()
            if not bid:
                continue
            control = control_from_battery_params(battery)
            keys = required_binding_keys(
                component_kind="battery",
                entity_id=bid,
                control=control,
                grid_tied_house=bid in grid_tied,
            )
            if missing_required_keys(battery.get("ehal_bindings"), keys):
                return True
        for inverter in components.get("inverters") or []:
            if not isinstance(inverter, dict):
                continue
            iid = str(inverter.get("id") or "").strip()
            if not iid:
                continue
            control = str(
                inverter.get("control") or DEFAULT_INVERTER_CONTROL
            ).strip().lower()
            has_pv = inverter_has_attached_pv(iid, pv_systems)
            keys = required_binding_keys(
                component_kind="inverter",
                entity_id=iid,
                control=control,
                has_attached_pv=has_pv,
            )
            if missing_required_keys(inverter.get("ehal_bindings"), keys):
                return True
        for pv in pv_systems:
            if not isinstance(pv, dict):
                continue
            pid = str(pv.get("id") or "").strip()
            if not pid:
                continue
            bindings = pv.get("ehal_bindings")
            if not isinstance(bindings, dict):
                continue
            # Empty optional per-PV production leftovers need stripping.
            from ehal.pv_fields import pv_field

            key = pv_field(pid, "sens_pv_production_active")
            if key in bindings and not str(bindings.get(key) or "").strip():
                return True
    return False
