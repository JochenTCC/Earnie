"""Structural migrate: batteries[].kind → inverters[] (2.7.l)."""
from __future__ import annotations

from house_config.inverter import (
    DEFAULT_INVERTER_EFFICIENCY,
    needs_inverter_migration,
)
from runtime_store.data_model import stamp_data_model


def migrate_components_inverters(doc: dict) -> tuple[dict, bool]:
    """Return (new_doc, changed). Idempotent when already migrated."""
    if not needs_inverter_migration(doc) and isinstance(doc.get("inverters"), list):
        if not any(
            isinstance(b, dict) and "kind" in b for b in (doc.get("batteries") or [])
        ):
            return doc, False

    out = dict(doc)
    batteries = list(out.get("batteries") or [])
    pv_systems = list(out.get("pv_systems") or [])
    inverters: list[dict] = []
    if isinstance(out.get("inverters"), list):
        inverters = [dict(i) for i in out["inverters"] if isinstance(i, dict)]

    existing_ids = {
        str(i.get("id") or "").strip()
        for i in inverters
        if str(i.get("id") or "").strip()
    }
    main_id = "wr_main"
    if main_id not in existing_ids:
        inverters.append(
            {
                "id": main_id,
                "label": "Haupt-Wechselrichter",
                "type": "hybrid",
                "ac_connection": "grid_tied",
                "control": "full",
                "efficiency": DEFAULT_INVERTER_EFFICIENCY,
                "ehal_bindings": {},
            }
        )
        existing_ids.add(main_id)

    new_batteries: list[dict] = []
    for bat in batteries:
        if not isinstance(bat, dict):
            continue
        bat_out = dict(bat)
        kind = str(bat_out.pop("kind", "") or "battery_inverter").strip().lower()
        bat_id = str(bat_out.get("id") or "").strip()
        bat_type = str(bat_out.get("type") or "house").strip().lower()
        backing = str(bat_out.get("backing") or "").strip().lower()
        if bat_type == "powerstation" and backing == "virtual":
            bat_out.pop("inverter_id", None)
            new_batteries.append(bat_out)
            continue
        if kind == "isolated":
            island_id = f"wr_{bat_id}" if bat_id else f"wr_island_{len(inverters)}"
            if island_id not in existing_ids:
                inverters.append(
                    {
                        "id": island_id,
                        "label": f"Powerstation-WR {bat_out.get('label') or bat_id}",
                        "type": "hybrid",
                        "ac_connection": "island",
                        "control": "full",
                        "efficiency": DEFAULT_INVERTER_EFFICIENCY,
                        "owned_by": bat_id,
                        "ehal_bindings": {},
                    }
                )
                existing_ids.add(island_id)
            bat_out["inverter_id"] = island_id
        else:
            bat_out["inverter_id"] = str(bat_out.get("inverter_id") or main_id)
        new_batteries.append(bat_out)

    new_pv: list[dict] = []
    for pv in pv_systems:
        if not isinstance(pv, dict):
            continue
        pv_out = dict(pv)
        if not str(pv_out.get("inverter_id") or "").strip():
            pv_out["inverter_id"] = main_id
        new_pv.append(pv_out)

    out["inverters"] = inverters
    out["batteries"] = new_batteries
    out["pv_systems"] = new_pv
    stamp_data_model(out)
    return out, True
