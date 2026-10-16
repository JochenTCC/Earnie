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


def needs_grid_meter_migration(doc: dict | None) -> bool:
    """True when plant.grid_meter is missing or incomplete."""
    if not isinstance(doc, dict):
        return False
    plant = doc.get("plant")
    if not isinstance(plant, dict):
        return True
    gm = plant.get("grid_meter")
    if not isinstance(gm, dict):
        return True
    return "at_house_connection" not in gm or "single_tariff" not in gm


def needs_topology_pack_migration(
    components_doc: dict | None,
    house_doc: dict | None,
) -> bool:
    """True when components or house_profiles still need Topology P1 seeds."""
    if isinstance(components_doc, dict) and needs_topology_migration(components_doc):
        return True
    return needs_grid_meter_migration(house_doc)


def migrate_house_profiles_grid_meter(doc: dict) -> tuple[dict, bool]:
    """Seed plant.grid_meter when missing. Return (doc, changed)."""
    if not isinstance(doc, dict):
        raise ValueError("house_profiles.json muss ein Objekt sein.")
    if not needs_grid_meter_migration(doc):
        return doc, False
    out = dict(doc)
    plant_raw = out.get("plant")
    plant = dict(plant_raw) if isinstance(plant_raw, dict) else {}
    plant["grid_meter"] = dict(DEFAULT_GRID_METER)
    out["plant"] = plant
    stamp_data_model(out)
    return out, True
