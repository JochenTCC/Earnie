"""One-shot Topology P1: house batteries[].regulates_on + plant.grid_meter seed."""
from __future__ import annotations

from house_config.powerstation import BATTERY_TYPE_HOUSE
from house_config.topology_regulates import (
    REGULATES_ON_GRID,
    TOPOLOGY_MIGRATE_HINT,
)
from runtime_store.data_model import stamp_data_model

DEFAULT_GRID_METER = {
    "at_house_connection": True,
    "single_tariff": True,
}


def needs_topology_migration(doc: dict) -> bool:
    """True when any house battery lacks regulates_on."""
    if not isinstance(doc, dict):
        return False
    batteries = doc.get("batteries")
    if not isinstance(batteries, list):
        return False
    for bat in batteries:
        if not isinstance(bat, dict):
            continue
        bat_type = str(bat.get("type") or BATTERY_TYPE_HOUSE).strip().lower()
        if bat_type != BATTERY_TYPE_HOUSE:
            continue
        if "regulates_on" not in bat:
            return True
    return False


def reject_if_needs_topology_migration(doc: dict, *, path: str = "") -> None:
    """Fail fast when house batteries lack regulates_on."""
    if not needs_topology_migration(doc):
        return
    where = f" ({path})" if path else ""
    raise ValueError(
        f"components.json{where}: house batteries[].regulates_on fehlt. "
        f"{TOPOLOGY_MIGRATE_HINT}"
    )


def migrate_components_topology(doc: dict) -> tuple[dict, list[str]]:
    """Set regulates_on=grid on house batteries missing it. Return (doc, ids)."""
    if not isinstance(doc, dict):
        raise ValueError("components.json muss ein Objekt sein.")
    if not needs_topology_migration(doc):
        return doc, []

    out = dict(doc)
    batteries_raw = list(out.get("batteries") or [])
    new_batteries: list[dict] = []
    migrated_ids: list[str] = []
    for bat in batteries_raw:
        if not isinstance(bat, dict):
            continue
        bat_out = dict(bat)
        bat_type = str(bat_out.get("type") or BATTERY_TYPE_HOUSE).strip().lower()
        bat_id = str(bat_out.get("id") or "").strip() or "?"
        if bat_type == BATTERY_TYPE_HOUSE and "regulates_on" not in bat_out:
            bat_out["regulates_on"] = REGULATES_ON_GRID
            migrated_ids.append(bat_id)
        new_batteries.append(bat_out)
    out["batteries"] = new_batteries
    stamp_data_model(out)
    return out, migrated_ids


def migrate_house_profiles_grid_meter(doc: dict) -> tuple[dict, bool]:
    """Seed plant.grid_meter when missing. Return (doc, changed)."""
    if not isinstance(doc, dict):
        raise ValueError("house_profiles.json muss ein Objekt sein.")
    plant_raw = doc.get("plant")
    plant = dict(plant_raw) if isinstance(plant_raw, dict) else {}
    if isinstance(plant.get("grid_meter"), dict):
        gm = plant["grid_meter"]
        if "at_house_connection" in gm and "single_tariff" in gm:
            return doc, False
    out = dict(doc)
    plant = dict(plant)
    plant["grid_meter"] = dict(DEFAULT_GRID_METER)
    out["plant"] = plant
    stamp_data_model(out)
    return out, True
