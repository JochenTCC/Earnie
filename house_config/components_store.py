"""Laden und Validieren von config/components.json (Batterien & PV-Anlagen)."""
from __future__ import annotations

import json
import os

from house_config.entity_resolution import normalize_battery, normalize_pv_system
from house_config.powerstation import apply_virtual_powerstation_inheritance


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {"batteries": [], "pv_systems": []}
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                return json.load(handle)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"components.json '{path}' ist weder UTF-8 noch cp1252 lesbar.")


def normalize_components_document(doc: dict) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("components.json muss ein Objekt sein.")
    batteries_raw = doc.get("batteries", [])
    pv_raw = doc.get("pv_systems", [])
    if not isinstance(batteries_raw, list):
        raise ValueError("batteries muss ein Array sein.")
    if not isinstance(pv_raw, list):
        raise ValueError("pv_systems muss ein Array sein.")
    batteries: list[dict] = []
    seen_battery_ids: set[str] = set()
    for index, item in enumerate(batteries_raw):
        if not isinstance(item, dict):
            raise ValueError(f"batteries[{index}] muss ein Objekt sein.")
        inherited = apply_virtual_powerstation_inheritance(item, batteries_raw)
        spec = normalize_battery(inherited, index)
        if spec["id"] in seen_battery_ids:
            raise ValueError(f"batteries: doppelte id '{spec['id']}'.")
        seen_battery_ids.add(spec["id"])
        batteries.append(spec)
    pv_systems: list[dict] = []
    seen_pv_ids: set[str] = set()
    for index, item in enumerate(pv_raw):
        spec = normalize_pv_system(item, index)
        if spec["id"] in seen_pv_ids:
            raise ValueError(f"pv_systems: doppelte id '{spec['id']}'.")
        seen_pv_ids.add(spec["id"])
        pv_systems.append(spec)
    return {"batteries": batteries, "pv_systems": pv_systems}


def load_components_document(path: str) -> dict:
    doc = _read_json(path)
    if not isinstance(doc, dict):
        raise ValueError("components.json muss ein Objekt sein.")
    batteries = doc.get("batteries", [])
    pv_systems = doc.get("pv_systems", [])
    if not isinstance(batteries, list):
        raise ValueError("batteries muss ein Array sein.")
    if not isinstance(pv_systems, list):
        raise ValueError("pv_systems muss ein Array sein.")
    return {"batteries": batteries, "pv_systems": pv_systems}


def _serialize_battery(spec: dict) -> dict:
    """Persist split charge/discharge limits (2.7.j); drop legacy single max."""
    bat_type = str(spec.get("type") or "house").strip().lower() or "house"
    out: dict = {
        "id": spec["id"],
        "label": spec["label"],
        "type": bat_type,
        "battery_capacity_kwh": spec["battery_capacity_kwh"],
        "battery_max_charge_power_kw": float(spec["battery_max_charge_power_kw"]),
        "battery_max_discharge_power_kw": float(spec["battery_max_discharge_power_kw"]),
        "battery_efficiency": spec["battery_efficiency"],
        "battery_min_soc": spec["battery_min_soc"],
        "battery_max_soc": spec["battery_max_soc"],
        "threshold_power": spec["threshold_power"],
        "limits_from_live": bool(spec.get("limits_from_live", False)),
        "kind": str(spec.get("kind") or "battery_inverter"),
        "control": str(spec.get("control") or "full"),
    }
    if bat_type == "powerstation":
        out["backing"] = str(spec.get("backing") or "virtual").strip().lower()
        out["role"] = str(spec.get("role") or "single_use").strip().lower()
        attached_ids = [
            str(cid).strip()
            for cid in (spec.get("attached_consumer_ids") or [])
            if str(cid or "").strip()
        ]
        if not attached_ids:
            singular = str(spec.get("attached_consumer_id") or "").strip()
            if singular:
                attached_ids = [singular]
        out["attached_consumer_ids"] = attached_ids
        out["attached_consumer_id"] = attached_ids[0] if attached_ids else ""
    standby = float(spec.get("standby_power_kw", 0.0) or 0.0)
    if standby > 0.0:
        out["standby_power_kw"] = standby
    bindings = spec.get("ehal_bindings")
    if isinstance(bindings, dict) and bindings:
        out["ehal_bindings"] = {
            str(k): str(v).strip() for k, v in bindings.items() if str(v or "").strip()
        }
    wear = spec.get("battery_wear")
    if wear is not None:
        out["battery_wear"] = wear
    return out


def _serialize_pv_system(spec: dict) -> dict:
    return {
        "id": spec["id"],
        "label": spec["label"],
        "kwp": spec["pv_kwp"],
        "pv_tilt": spec["pv_tilt"],
        "pv_azimuth": spec["pv_azimuth"],
    }


def save_components_document(path: str, doc: dict) -> None:
    from runtime_store.data_model import stamp_data_model

    normalized = normalize_components_document(doc)
    serializable = {
        "batteries": [_serialize_battery(item) for item in normalized["batteries"]],
        "pv_systems": [_serialize_pv_system(item) for item in normalized["pv_systems"]],
    }
    stamp_data_model(serializable)
    target = os.path.abspath(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(serializable, handle, indent=4, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, target)
