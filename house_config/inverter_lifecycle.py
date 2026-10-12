"""Owned island inverter create/drop for physical powerstations (Inverter P2)."""
from __future__ import annotations

from house_config.inverter import (
    AC_ISLAND,
    DEFAULT_INVERTER_CONTROL,
    DEFAULT_INVERTER_EFFICIENCY,
    INVERTER_TYPE_HYBRID,
)
from house_config.powerstation import BACKING_VIRTUAL, BATTERY_TYPE_POWERSTATION


def owned_island_inverter_id(battery_id: str) -> str:
    bat_id = str(battery_id or "").strip()
    if not bat_id:
        raise ValueError("battery_id fehlt für Insel-Wechselrichter.")
    return f"wr_{bat_id}"


def is_physical_powerstation(battery: dict) -> bool:
    bat_type = str(battery.get("type") or "house").strip().lower()
    backing = str(battery.get("backing") or "").strip().lower()
    return bat_type == BATTERY_TYPE_POWERSTATION and backing != BACKING_VIRTUAL


def drop_owned_inverters(
    inverters: list[dict],
    *,
    battery_id: str,
    keep_id: str = "",
) -> list[dict]:
    """Remove inverters owned by battery_id except keep_id."""
    bat = str(battery_id or "").strip()
    keep = str(keep_id or "").strip()
    out: list[dict] = []
    for item in inverters:
        if not isinstance(item, dict):
            continue
        owned = str(item.get("owned_by") or "").strip()
        inv_id = str(item.get("id") or "").strip()
        if owned == bat and inv_id != keep:
            continue
        out.append(item)
    return out


def ensure_owned_island_inverter(
    inverters: list[dict],
    *,
    battery_id: str,
    battery_label: str,
) -> tuple[list[dict], str]:
    """Ensure a hybrid island inverter owned by the battery; return (list, inv_id)."""
    bat_id = str(battery_id or "").strip()
    if not bat_id:
        raise ValueError("battery_id fehlt für owned island inverter.")
    inv_id = owned_island_inverter_id(bat_id)
    label = str(battery_label or bat_id).strip() or bat_id
    cleaned = drop_owned_inverters(inverters, battery_id=bat_id, keep_id=inv_id)
    existing = next(
        (
            item
            for item in cleaned
            if isinstance(item, dict) and str(item.get("id") or "").strip() == inv_id
        ),
        None,
    )
    if existing is None:
        cleaned.append(
            {
                "id": inv_id,
                "label": f"Insel-WR {label}",
                "type": INVERTER_TYPE_HYBRID,
                "ac_connection": AC_ISLAND,
                "control": DEFAULT_INVERTER_CONTROL,
                "efficiency": DEFAULT_INVERTER_EFFICIENCY,
                "owned_by": bat_id,
                "ehal_bindings": {},
            }
        )
        return cleaned, inv_id
    updated = dict(existing)
    updated["owned_by"] = bat_id
    updated["ac_connection"] = AC_ISLAND
    if str(updated.get("type") or "").strip().lower() not in {
        INVERTER_TYPE_HYBRID,
        "hybrid",
    }:
        updated["type"] = INVERTER_TYPE_HYBRID
    replaced = [
        updated if str(item.get("id") or "").strip() == inv_id else item
        for item in cleaned
    ]
    return replaced, inv_id


def rebind_owned_by(
    inverters: list[dict],
    *,
    old_battery_id: str,
    new_battery_id: str,
) -> list[dict]:
    """Rewrite owned_by when a battery Kennung changes."""
    old = str(old_battery_id or "").strip()
    new = str(new_battery_id or "").strip()
    if not old or not new or old == new:
        return inverters
    out: list[dict] = []
    for item in inverters:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if str(row.get("owned_by") or "").strip() == old:
            row["owned_by"] = new
        out.append(row)
    return out


def inverter_refs_blocking_delete(
    *,
    inverter_id: str,
    batteries: list[dict],
    pv_systems: list[dict],
    exclude_battery_id: str = "",
) -> list[str]:
    """Human-readable refs that still point at inverter_id."""
    target = str(inverter_id or "").strip()
    exclude = str(exclude_battery_id or "").strip()
    refs: list[str] = []
    for bat in batteries:
        if not isinstance(bat, dict):
            continue
        bid = str(bat.get("id") or "").strip()
        if bid == exclude:
            continue
        if str(bat.get("inverter_id") or "").strip() == target:
            refs.append(f"Batterie '{bid}'")
    for pv in pv_systems:
        if not isinstance(pv, dict):
            continue
        pid = str(pv.get("id") or "").strip()
        if str(pv.get("inverter_id") or "").strip() == target:
            refs.append(f"PV-Anlage '{pid}'")
    return refs
