"""One-shot: split lumped battery_efficiency into η_inv + η_batt.

Today's batteries[].battery_efficiency is treated as lumped path
η_old ≈ η_inv · η_batt. After migrate:

- inverters[].efficiency = η_inv (default 0.97 if missing)
- batteries[].battery_efficiency = η_batt = η_old / η_inv (clamped to (0, 1])
"""
from __future__ import annotations

from house_config.inverter import (
    DEFAULT_INVERTER_EFFICIENCY,
    needs_conversion_efficiency_migration,
)
from house_config.powerstation import (
    is_virtual_powerstation,
    primary_house_battery,
)


def _clamp_eta(value: float) -> float:
    if value <= 0.0:
        return 1e-9
    if value > 1.0:
        return 1.0
    return value


def _eta_inv_for_battery(
    bat: dict,
    *,
    inv_by_id: dict[str, dict],
    primary_house: dict | None,
) -> float:
    if is_virtual_powerstation(bat):
        if primary_house is None:
            raise ValueError(
                f"Batterie '{bat.get('id')}': virtuelle Powerstation ohne "
                "Hausbatterie — η_inv nicht ableitbar."
            )
        inv_id = str(primary_house.get("inverter_id") or "").strip()
    else:
        inv_id = str(bat.get("inverter_id") or "").strip()
    if not inv_id:
        raise ValueError(
            f"Batterie '{bat.get('id')}': inverter_id fehlt für η_inv-Migration."
        )
    inv = inv_by_id.get(inv_id)
    if inv is None:
        raise ValueError(
            f"Batterie '{bat.get('id')}': unbekannte inverter_id '{inv_id}'."
        )
    return float(inv["efficiency"])


def migrate_components_conversion_efficiency(doc: dict) -> tuple[dict, bool]:
    """Return (new_doc, changed). Idempotent when every inverter has efficiency."""
    if not isinstance(doc, dict):
        raise ValueError("components.json muss ein Objekt sein.")
    if not needs_conversion_efficiency_migration(doc):
        return doc, False

    out = dict(doc)
    inverters_raw = list(out.get("inverters") or [])
    batteries_raw = list(out.get("batteries") or [])

    new_inverters: list[dict] = []
    for inv in inverters_raw:
        if not isinstance(inv, dict):
            continue
        inv_out = dict(inv)
        if "efficiency" not in inv_out:
            inv_out["efficiency"] = DEFAULT_INVERTER_EFFICIENCY
        new_inverters.append(inv_out)

    inv_by_id = {
        str(i.get("id") or "").strip(): i
        for i in new_inverters
        if str(i.get("id") or "").strip()
    }
    primary = primary_house_battery(batteries_raw)

    new_batteries: list[dict] = []
    for bat in batteries_raw:
        if not isinstance(bat, dict):
            continue
        bat_out = dict(bat)
        if "battery_efficiency" not in bat_out:
            new_batteries.append(bat_out)
            continue
        eta_old = float(bat_out["battery_efficiency"])
        eta_inv = _eta_inv_for_battery(
            bat_out, inv_by_id=inv_by_id, primary_house=primary
        )
        bat_out["battery_efficiency"] = _clamp_eta(eta_old / eta_inv)
        new_batteries.append(bat_out)

    out["inverters"] = new_inverters
    out["batteries"] = new_batteries
    return out, True
