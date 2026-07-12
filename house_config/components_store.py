"""Laden und Validieren von config/components.json (Batterien & PV-Anlagen)."""
from __future__ import annotations

import json
import os

from house_config.entity_resolution import normalize_battery, normalize_pv_system


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
        spec = normalize_battery(item, index)
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
    out: dict = {
        "id": spec["id"],
        "label": spec["label"],
        "battery_capacity_kwh": spec["battery_capacity_kwh"],
        "battery_max_power_kw": spec["battery_max_power_kw"],
        "battery_efficiency": spec["battery_efficiency"],
        "battery_min_soc": spec["battery_min_soc"],
        "battery_max_soc": spec["battery_max_soc"],
        "threshold_power": spec["threshold_power"],
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
    normalized = normalize_components_document(doc)
    serializable = {
        "batteries": [_serialize_battery(item) for item in normalized["batteries"]],
        "pv_systems": [_serialize_pv_system(item) for item in normalized["pv_systems"]],
    }
    target = os.path.abspath(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(serializable, handle, indent=4, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, target)
