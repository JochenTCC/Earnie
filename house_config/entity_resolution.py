"""Auflösung von batteries[] und pv_systems[] in flache runtime_settings-Felder."""
from __future__ import annotations

from house_config.battery_control import (
    DEFAULT_BATTERY_CONTROL,
    normalize_battery_control,
)
from house_config.battery_kind import (
    DEFAULT_BATTERY_KIND,
    normalize_battery_kind,
)
from house_config.powerstation import (
    BATTERY_TYPE_HOUSE,
    BATTERY_TYPE_POWERSTATION,
    is_powerstation,
    normalize_battery_type,
    normalize_powerstation_fields,
)

ZERO_BATTERY_FLAT = {
    "battery_capacity_kwh": 0.0,
    "battery_max_power_kw": 0.0,
    "battery_max_charge_power_kw": 0.0,
    "battery_max_discharge_power_kw": 0.0,
    "battery_efficiency": 1.0,
    "battery_min_soc": 0.0,
    "battery_max_soc": 100.0,
    "threshold_power": 0.02,
    "standby_power_kw": 0.0,
    "battery_control": DEFAULT_BATTERY_CONTROL,
    "battery_kind": DEFAULT_BATTERY_KIND,
    "limits_from_live": False,
}

ZERO_PV_FLAT = {
    "pv_kwp": 0.0,
    "pv_tilt": 0.0,
    "pv_azimuth": 0.0,
}


def strip_assets_for_reference(params: dict) -> dict:
    """Referenz-Gegenfactual: gleiches Profil/Tarif, keine Batterie, keine PV."""
    out = dict(params)
    out.update(ZERO_BATTERY_FLAT)
    out.update(ZERO_PV_FLAT)
    for key in (
        "battery_id",
        "battery_ids",
        "pv_system_id",
        "pv_system_ids",
        "_battery_wear",
        "_planning_batteries",
        "_planning_powerstations",
        "_planning_pv_systems",
    ):
        out.pop(key, None)
    return out


def normalize_battery_ids(settings: dict) -> list[str]:
    """Return unique ``battery_ids``; reject singular legacy ``battery_id``."""
    if "battery_id" in settings:
        raise ValueError(
            "settings.battery_id ist nicht mehr unterstützt — "
            "bitte battery_ids[] verwenden."
        )
    ids: list[str] = []
    raw_list = settings.get("battery_ids")
    if isinstance(raw_list, list):
        for item in raw_list:
            bat_id = str(item or "").strip()
            if bat_id and bat_id not in ids:
                ids.append(bat_id)
    return ids


def normalize_pv_system_ids(settings: dict) -> list[str]:
    """Return unique ``pv_system_ids``; reject singular legacy ``pv_system_id``."""
    if "pv_system_id" in settings:
        raise ValueError(
            "settings.pv_system_id ist nicht mehr unterstützt — "
            "bitte pv_system_ids[] verwenden."
        )
    ids: list[str] = []
    raw_list = settings.get("pv_system_ids")
    if isinstance(raw_list, list):
        for item in raw_list:
            pv_id = str(item or "").strip()
            if pv_id and pv_id not in ids:
                ids.append(pv_id)
    return ids


def planning_pv_entry(pv: dict) -> dict:
    """Stable planning-shape entry for a resolved PV system."""
    return {
        "id": pv["id"],
        "label": pv["label"],
        "pv_kwp": float(pv["pv_kwp"]),
        "pv_tilt": float(pv["pv_tilt"]),
        "pv_azimuth": float(pv["pv_azimuth"]),
    }


def split_battery_max_power_kw(raw: dict, *, battery_id: str = "?", index: int = 0) -> tuple[float, float]:
    """Resolve charge/discharge max kW; migrate legacy ``battery_max_power_kw``."""
    charge_raw = raw.get("battery_max_charge_power_kw")
    discharge_raw = raw.get("battery_max_discharge_power_kw")
    legacy_raw = raw.get("battery_max_power_kw")
    try:
        legacy = float(legacy_raw) if legacy_raw is not None else None
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): battery_max_power_kw ungültig."
        ) from exc
    try:
        charge = float(charge_raw) if charge_raw is not None else None
        discharge = float(discharge_raw) if discharge_raw is not None else None
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): "
            "battery_max_charge/discharge_power_kw ungültig."
        ) from exc
    if charge is None and discharge is None:
        if legacy is None:
            raise ValueError(
                f"batteries[{index}] ('{battery_id}'): "
                "battery_max_charge_power_kw / battery_max_discharge_power_kw "
                "(oder legacy battery_max_power_kw) fehlt."
            )
        charge = legacy
        discharge = legacy
    elif charge is None:
        charge = discharge if discharge is not None else legacy
    elif discharge is None:
        discharge = charge if charge is not None else legacy
    if charge is None or discharge is None:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): Lade-/Entladeleistung unvollständig."
        )
    if charge < 0.0 or discharge < 0.0:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): "
            "battery_max_charge/discharge_power_kw muss >= 0 sein."
        )
    # Zero battery / reference strip: both may be 0. Positive house configs need
    # both > 0. Powerstations (2.7.g) may charge-only (discharge 0 = no house feed).
    bat_type = str(raw.get("type") or BATTERY_TYPE_HOUSE).strip().lower()
    if bat_type != BATTERY_TYPE_POWERSTATION and bool(charge) != bool(discharge):
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): "
            "battery_max_charge/discharge_power_kw müssen beide 0 oder beide > 0 sein."
        )
    return float(charge), float(discharge)


def normalize_battery(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"batteries[{index}] muss ein Objekt sein.")
    battery_id = str(raw.get("id", "")).strip()
    if not battery_id:
        raise ValueError(f"batteries[{index}]: id fehlt.")
    label = str(raw.get("label", battery_id)).strip() or battery_id
    threshold = float(raw.get("threshold_power", 0.02))
    if threshold <= 0.0 or threshold > 1.0:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): threshold_power muss in (0, 1] liegen."
        )
    standby = float(raw.get("standby_power_kw", 0.0) or 0.0)
    if standby < 0.0:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): standby_power_kw muss >= 0 sein."
        )
    control = normalize_battery_control(
        raw.get("control"), battery_id=battery_id, index=index
    )
    kind = normalize_battery_kind(
        raw.get("kind"), battery_id=battery_id, index=index
    )
    charge_kw, discharge_kw = split_battery_max_power_kw(
        raw, battery_id=battery_id, index=index
    )
    bat_type = normalize_battery_type(
        raw.get("type"), battery_id=battery_id, index=index
    )
    capacity = float(raw["battery_capacity_kwh"])
    if bat_type == BATTERY_TYPE_POWERSTATION:
        if capacity > 0.0 and charge_kw <= 0.0:
            raise ValueError(
                f"batteries[{index}] ('{battery_id}'): "
                "powerstation battery_max_charge_power_kw muss > 0 sein."
            )
        # Physical one-way packs cannot feed the house grid; discharge may be 0.
        discharge_kw = max(0.0, discharge_kw)
    elif capacity > 0.0 and (charge_kw <= 0.0 or discharge_kw <= 0.0):
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): "
            "battery_max_charge/discharge_power_kw muss > 0 sein."
        )
    ehal_bindings = raw.get("ehal_bindings")
    if ehal_bindings is None:
        ehal_bindings = {}
    if not isinstance(ehal_bindings, dict):
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): ehal_bindings muss ein Objekt sein."
        )
    out = {
        "id": battery_id,
        "label": label,
        "type": bat_type,
        "kind": kind,
        "battery_capacity_kwh": capacity,
        "battery_max_charge_power_kw": charge_kw,
        "battery_max_discharge_power_kw": discharge_kw,
        # Legacy alias = max(charge, discharge) for threshold / straggler callers.
        "battery_max_power_kw": max(charge_kw, discharge_kw),
        "battery_efficiency": float(raw["battery_efficiency"]),
        "battery_min_soc": float(raw["battery_min_soc"]),
        "battery_max_soc": float(raw["battery_max_soc"]),
        "threshold_power": threshold,
        "standby_power_kw": standby,
        "control": control,
        "limits_from_live": bool(raw.get("limits_from_live", False)),
        "ehal_bindings": {
            str(k): str(v).strip()
            for k, v in ehal_bindings.items()
            if str(v or "").strip()
        },
        "battery_wear": _normalize_battery_wear(raw.get("battery_wear"), battery_id, index),
    }
    if bat_type == BATTERY_TYPE_POWERSTATION:
        out.update(
            normalize_powerstation_fields(raw, battery_id=battery_id, index=index)
        )
    if "id_locked" in raw:
        out["id_locked"] = bool(raw.get("id_locked"))
    provisional = str(raw.get("id_provisional_label") or "").strip()
    if provisional and not out.get("id_locked", True):
        out["id_provisional_label"] = provisional
    return out


def _normalize_battery_wear(raw: object, battery_id: str, index: int) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): battery_wear muss ein Objekt sein."
        )
    from optimizer.battery_wear import validate_battery_wear_config

    return validate_battery_wear_config(raw)


def battery_wear_cent_per_kwh(battery: dict, capacity_kwh: float | None = None) -> float:
    """Verschleiß ct/kWh aus batteries[]-Eintrag (kein globaler Fallback)."""
    from optimizer.battery_wear import battery_wear_cent_per_kwh_from_config

    wear_raw = battery.get("battery_wear")
    if wear_raw is None:
        raise ValueError(
            f"Batterie '{battery.get('id', '?')}': battery_wear fehlt in batteries[]."
        )
    cap = float(capacity_kwh if capacity_kwh is not None else battery["battery_capacity_kwh"])
    return battery_wear_cent_per_kwh_from_config(wear_raw, cap)


def normalize_pv_system(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"pv_systems[{index}] muss ein Objekt sein.")
    pv_id = str(raw.get("id", "")).strip()
    if not pv_id:
        raise ValueError(f"pv_systems[{index}]: id fehlt.")
    label = str(raw.get("label", pv_id)).strip() or pv_id
    kwp = float(raw["kwp"])
    if kwp <= 0.0:
        raise ValueError(f"pv_systems[{index}] ('{pv_id}'): kwp muss > 0 sein.")
    out = {
        "id": pv_id,
        "label": label,
        "pv_kwp": kwp,
        "pv_tilt": float(raw.get("pv_tilt", raw.get("tilt", 0.0))),
        "pv_azimuth": float(raw.get("pv_azimuth", raw.get("azimuth", 0.0))),
    }
    if "id_locked" in raw:
        out["id_locked"] = bool(raw.get("id_locked"))
    provisional = str(raw.get("id_provisional_label") or "").strip()
    if provisional and not out.get("id_locked", True):
        out["id_provisional_label"] = provisional
    return out


def batteries_by_id(raw_config: dict) -> dict[str, dict]:
    raw_list = raw_config.get("batteries")
    if raw_list is None:
        return {}
    if not isinstance(raw_list, list):
        raise ValueError("batteries muss ein Array sein.")
    result: dict[str, dict] = {}
    for index, item in enumerate(raw_list):
        spec = normalize_battery(item, index)
        if spec["id"] in result:
            raise ValueError(f"batteries: doppelte id '{spec['id']}'.")
        result[spec["id"]] = spec
    return result


def pv_systems_by_id(raw_config: dict) -> dict[str, dict]:
    raw_list = raw_config.get("pv_systems")
    if raw_list is None:
        return {}
    if not isinstance(raw_list, list):
        raise ValueError("pv_systems muss ein Array sein.")
    result: dict[str, dict] = {}
    for index, item in enumerate(raw_list):
        spec = normalize_pv_system(item, index)
        if spec["id"] in result:
            raise ValueError(f"pv_systems: doppelte id '{spec['id']}'.")
        result[spec["id"]] = spec
    return result


def planning_battery_entry(bat: dict) -> dict:
    """Stable planning-shape entry for a resolved battery (runtime/MILP)."""
    entry = {
        "id": bat["id"],
        "label": bat["label"],
        "type": bat.get("type", BATTERY_TYPE_HOUSE),
        "kind": bat.get("kind", DEFAULT_BATTERY_KIND),
        "battery_capacity_kwh": float(bat["battery_capacity_kwh"]),
        "battery_max_charge_power_kw": float(bat["battery_max_charge_power_kw"]),
        "battery_max_discharge_power_kw": float(bat["battery_max_discharge_power_kw"]),
        "battery_max_power_kw": float(bat["battery_max_power_kw"]),
        "battery_efficiency": float(bat["battery_efficiency"]),
        "battery_min_soc": float(bat["battery_min_soc"]),
        "battery_max_soc": float(bat["battery_max_soc"]),
        "threshold_power": float(bat["threshold_power"]),
        "standby_power_kw": float(bat.get("standby_power_kw", 0.0) or 0.0),
        "control": bat.get("control", DEFAULT_BATTERY_CONTROL),
        "limits_from_live": bool(bat.get("limits_from_live", False)),
        "ehal_bindings": dict(bat.get("ehal_bindings") or {}),
        "battery_wear": (
            dict(bat["battery_wear"]) if bat.get("battery_wear") is not None else None
        ),
    }
    if is_powerstation(bat):
        entry["backing"] = bat["backing"]
        entry["role"] = bat["role"]
        entry["attached_consumer_ids"] = list(bat.get("attached_consumer_ids") or [])
        entry["attached_consumer_id"] = bat.get("attached_consumer_id") or (
            entry["attached_consumer_ids"][0] if entry["attached_consumer_ids"] else ""
        )
    return entry


def battery_params_from_planning(entry: dict) -> dict:
    """Optimizer-shaped params dict from a planning battery entry."""
    bat_id = entry["id"]
    out = {
        "id": bat_id,
        "label": str(entry.get("label") or bat_id).strip() or bat_id,
        "type": entry.get("type", BATTERY_TYPE_HOUSE),
        "kind": entry.get("kind", DEFAULT_BATTERY_KIND),
        "battery_capacity_kwh": float(entry["battery_capacity_kwh"]),
        "min_soc": float(entry["battery_min_soc"]),
        "max_soc": float(entry["battery_max_soc"]),
        "max_charge_power_kw": float(entry["battery_max_charge_power_kw"]),
        "max_discharge_power_kw": float(entry["battery_max_discharge_power_kw"]),
        "max_power_kw": float(entry["battery_max_power_kw"]),
        "efficiency": float(entry["battery_efficiency"]),
        "standby_power_kw": float(entry.get("standby_power_kw", 0.0) or 0.0),
        "threshold_power": float(entry.get("threshold_power", 0.02) or 0.02),
        "control": str(entry.get("control", DEFAULT_BATTERY_CONTROL) or DEFAULT_BATTERY_CONTROL),
        "limits_from_live": bool(entry.get("limits_from_live", False)),
        "ehal_bindings": dict(entry.get("ehal_bindings") or {}),
    }
    if is_powerstation(entry):
        out["backing"] = entry.get("backing")
        out["role"] = entry.get("role")
        attached_ids = list(entry.get("attached_consumer_ids") or [])
        out["attached_consumer_ids"] = attached_ids
        out["attached_consumer_id"] = entry.get("attached_consumer_id") or (
            next(iter(attached_ids), "")
        )
    return out


def resolve_battery_into_settings(
    settings: dict,
    batteries: dict[str, dict],
) -> dict:
    """Resolve ``battery_ids`` into ``_planning_batteries`` + flat fields.

    Flat fields use the first selected battery for singular callers; standby and
    max discharge powers are also summed for house-level aggregates.
    Inline flat battery fields (no ``battery_ids``) remain supported for
    scenarios that embed capacity/power directly.
    """
    out = dict(settings)
    if "battery_id" in out:
        raise ValueError(
            "settings.battery_id ist nicht mehr unterstützt — "
            "bitte battery_ids[] verwenden."
        )
    bat_ids = normalize_battery_ids(out)
    out.pop("battery_ids", None)

    # Powerstations are never selected via scenario battery_ids — attach via consumers.
    all_powerstations = [
        planning_battery_entry(bat)
        for bat in batteries.values()
        if is_powerstation(bat)
    ]
    out["_planning_powerstations"] = all_powerstations

    if not bat_ids:
        out["_planning_batteries"] = []
        if "battery_capacity_kwh" not in out:
            out.update(ZERO_BATTERY_FLAT)
        return out

    planning: list[dict] = []
    skipped_powerstations: list[str] = []
    for bat_id in bat_ids:
        if bat_id not in batteries:
            raise ValueError(f"Unbekannte battery_id '{bat_id}'.")
        bat = batteries[bat_id]
        if is_powerstation(bat):
            # Soft-skip: converting a house battery already listed in scenario
            # battery_ids must not hard-fail config reload (HK auto-save).
            skipped_powerstations.append(bat_id)
            continue
        planning.append(planning_battery_entry(bat))
    if skipped_powerstations:
        import logging

        logging.getLogger(__name__).warning(
            "battery_ids enthielt Powerstation(s) %s — ignoriert "
            "(Anbindung über appliance_recommendation.powerstation_id).",
            skipped_powerstations,
        )
    if not planning:
        out["_planning_batteries"] = []
        if "battery_capacity_kwh" not in out:
            out.update(ZERO_BATTERY_FLAT)
        return out

    out["_planning_batteries"] = planning
    first = planning[0]
    out.update(
        {
            "battery_capacity_kwh": first["battery_capacity_kwh"],
            "battery_max_charge_power_kw": first["battery_max_charge_power_kw"],
            "battery_max_discharge_power_kw": first["battery_max_discharge_power_kw"],
            "battery_max_power_kw": first["battery_max_power_kw"],
            "battery_efficiency": first["battery_efficiency"],
            "battery_min_soc": first["battery_min_soc"],
            "battery_max_soc": first["battery_max_soc"],
            "threshold_power": first["threshold_power"],
            "standby_power_kw": sum(
                float(b.get("standby_power_kw", 0.0) or 0.0) for b in planning
            ),
            "battery_control": first.get("control", DEFAULT_BATTERY_CONTROL),
            "battery_kind": first.get("kind", DEFAULT_BATTERY_KIND),
            "limits_from_live": bool(first.get("limits_from_live", False)),
        }
    )
    # Aggregates used by export unconstrained / house load
    out["_battery_max_discharge_power_kw_sum"] = sum(
        float(b["battery_max_discharge_power_kw"]) for b in planning
    )
    if first.get("battery_wear") is not None:
        out["_battery_wear"] = dict(first["battery_wear"])
    return out


def resolve_pv_into_settings(settings: dict, pv_systems: dict[str, dict]) -> dict:
    """Resolve ``pv_system_ids`` into planning + flat fields.

    Injects ``_planning_pv_systems`` (one entry per selected system). Sets ``pv_kwp``
    to the sum of selected systems. When exactly one system is selected, also sets
    ``pv_tilt`` / ``pv_azimuth`` for legacy single-surface callers.
    """
    out = dict(settings)
    pv_ids = normalize_pv_system_ids(out)
    out.pop("pv_system_ids", None)

    if not pv_ids:
        out["_planning_pv_systems"] = []
        if "pv_kwp" not in out:
            out.update(ZERO_PV_FLAT)
        return out

    planning: list[dict] = []
    for pv_id in pv_ids:
        if pv_id not in pv_systems:
            raise ValueError(f"Unbekannte pv_system_id '{pv_id}'.")
        planning.append(planning_pv_entry(pv_systems[pv_id]))

    out["_planning_pv_systems"] = planning
    out["pv_kwp"] = sum(float(item["pv_kwp"]) for item in planning)
    if len(planning) == 1:
        out["pv_tilt"] = float(planning[0]["pv_tilt"])
        out["pv_azimuth"] = float(planning[0]["pv_azimuth"])
    else:
        out.pop("pv_tilt", None)
        out.pop("pv_azimuth", None)
    return out
