"""Laden und Validieren von config/components.json (Batterien, PV, Wechselrichter)."""
from __future__ import annotations

import json
import os

from house_config.entity_resolution import normalize_battery, normalize_pv_system
from house_config.inverter import (
    normalize_inverter,
    reject_if_needs_conversion_efficiency_migration,
    reject_if_needs_inverter_migration,
    validate_inverter_topology,
)
from house_config.migrate_topology import reject_if_needs_topology_migration
from house_config.powerstation import apply_virtual_powerstation_inheritance


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {"inverters": [], "batteries": [], "pv_systems": []}
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
    reject_if_needs_inverter_migration(doc)
    reject_if_needs_conversion_efficiency_migration(doc)
    reject_if_needs_topology_migration(doc)
    inverters_raw = doc.get("inverters", [])
    batteries_raw = doc.get("batteries", [])
    pv_raw = doc.get("pv_systems", [])
    if not isinstance(inverters_raw, list):
        raise ValueError("inverters muss ein Array sein.")
    if not isinstance(batteries_raw, list):
        raise ValueError("batteries muss ein Array sein.")
    if not isinstance(pv_raw, list):
        raise ValueError("pv_systems muss ein Array sein.")
    inverters: list[dict] = []
    seen_inv: set[str] = set()
    for index, item in enumerate(inverters_raw):
        spec = normalize_inverter(item, index)
        if spec["id"] in seen_inv:
            raise ValueError(f"inverters: doppelte id '{spec['id']}'.")
        seen_inv.add(spec["id"])
        inverters.append(spec)
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
    validate_inverter_topology(
        inverters={i["id"]: i for i in inverters},
        batteries={b["id"]: b for b in batteries},
        pv_systems={p["id"]: p for p in pv_systems},
    )
    return {
        "inverters": inverters,
        "batteries": batteries,
        "pv_systems": pv_systems,
    }


def load_components_document(path: str) -> dict:
    doc = _read_json(path)
    if not isinstance(doc, dict):
        raise ValueError("components.json muss ein Objekt sein.")
    reject_if_needs_inverter_migration(doc, path=path)
    reject_if_needs_conversion_efficiency_migration(doc, path=path)
    reject_if_needs_topology_migration(doc, path=path)
    inverters = doc.get("inverters", [])
    batteries = doc.get("batteries", [])
    pv_systems = doc.get("pv_systems", [])
    if not isinstance(inverters, list):
        raise ValueError("inverters muss ein Array sein.")
    if not isinstance(batteries, list):
        raise ValueError("batteries muss ein Array sein.")
    if not isinstance(pv_systems, list):
        raise ValueError("pv_systems muss ein Array sein.")
    out = {
        "inverters": inverters,
        "batteries": batteries,
        "pv_systems": pv_systems,
    }
    try:
        from runtime_store.shadow.mode import is_shadow_config_readonly

        if is_shadow_config_readonly():
            from runtime_store.shadow.ehal_overlay import apply_overlay_to_components

            return apply_overlay_to_components(out)
    except Exception:
        pass
    return out


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
        "control": str(spec.get("control") or "full"),
    }
    if bat_type == "house" and spec.get("regulates_on") is not None:
        out["regulates_on"] = str(spec["regulates_on"]).strip().lower()
    inv_id = str(spec.get("inverter_id") or "").strip()
    if inv_id:
        out["inverter_id"] = inv_id
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
            str(k): str(v).strip()
            for k, v in bindings.items()
            if str(k or "").strip()
        }
    wear = spec.get("battery_wear")
    if wear is not None:
        out["battery_wear"] = wear
    if "id_locked" in spec:
        out["id_locked"] = bool(spec.get("id_locked"))
    provisional = str(spec.get("id_provisional_label") or "").strip()
    if provisional and not out.get("id_locked", True):
        out["id_provisional_label"] = provisional
    return out


def _serialize_pv_system(spec: dict) -> dict:
    out = {
        "id": spec["id"],
        "label": spec["label"],
        "kwp": spec["pv_kwp"],
        "pv_tilt": spec["pv_tilt"],
        "pv_azimuth": spec["pv_azimuth"],
        "inverter_id": str(spec.get("inverter_id") or "").strip(),
    }
    bindings = spec.get("ehal_bindings")
    if isinstance(bindings, dict) and bindings:
        out["ehal_bindings"] = {
            str(k): str(v).strip()
            for k, v in bindings.items()
            if str(k or "").strip()
        }
    if "id_locked" in spec:
        out["id_locked"] = bool(spec.get("id_locked"))
    provisional = str(spec.get("id_provisional_label") or "").strip()
    if provisional and not out.get("id_locked", True):
        out["id_provisional_label"] = provisional
    return out


def _serialize_inverter(spec: dict) -> dict:
    out: dict = {
        "id": spec["id"],
        "label": spec["label"],
        "type": spec["type"],
        "ac_connection": spec["ac_connection"],
        "control": str(spec.get("control") or "full"),
        "efficiency": float(spec["efficiency"]),
    }
    for field in (
        "max_ac_power_kw",
        "max_pv_input_kw",
        "max_ac_charge_kw",
        "owned_by",
        "regulates_on",
    ):
        if field in spec and spec[field] is not None and spec[field] != "":
            out[field] = spec[field]
    bindings = spec.get("ehal_bindings")
    if isinstance(bindings, dict) and bindings:
        out["ehal_bindings"] = {
            str(k): str(v).strip()
            for k, v in bindings.items()
            if str(k or "").strip()
        }
    if "id_locked" in spec:
        out["id_locked"] = bool(spec.get("id_locked"))
    provisional = str(spec.get("id_provisional_label") or "").strip()
    if provisional and not out.get("id_locked", True):
        out["id_provisional_label"] = provisional
    return out


def save_components_document(path: str, doc: dict) -> None:
    from runtime_store.data_model import stamp_data_model

    try:
        from runtime_store.shadow.mode import is_shadow_config_readonly

        if is_shadow_config_readonly():
            from runtime_store.shadow.errors import ConfigReadOnlyError

            raise ConfigReadOnlyError(
                f"Shadow mode: refusing write to components.json ({path})"
            )
    except ImportError:
        pass

    normalized = normalize_components_document(doc)
    serializable = {
        "inverters": [_serialize_inverter(item) for item in normalized["inverters"]],
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
