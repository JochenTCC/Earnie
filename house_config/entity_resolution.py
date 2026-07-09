"""Auflösung von batteries[] und pv_systems[] in flache runtime_settings-Felder."""
from __future__ import annotations


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
    return {
        "id": battery_id,
        "label": label,
        "battery_capacity_kwh": float(raw["battery_capacity_kwh"]),
        "battery_max_power_kw": float(raw["battery_max_power_kw"]),
        "battery_efficiency": float(raw["battery_efficiency"]),
        "battery_min_soc": float(raw["battery_min_soc"]),
        "battery_max_soc": float(raw["battery_max_soc"]),
        "threshold_power": threshold,
    }


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
    return {
        "id": pv_id,
        "label": label,
        "pv_kwp": kwp,
        "pv_tilt": float(raw.get("pv_tilt", raw.get("tilt", 0.0))),
        "pv_azimuth": float(raw.get("pv_azimuth", raw.get("azimuth", 0.0))),
    }


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


def resolve_battery_into_settings(settings: dict, batteries: dict[str, dict]) -> dict:
    """Ersetzt battery_id durch flache Batterie-Felder (falls gesetzt)."""
    out = dict(settings)
    battery_id = out.pop("battery_id", None)
    if not battery_id:
        return out
    battery_id = str(battery_id).strip()
    if battery_id not in batteries:
        raise ValueError(f"Unbekannte battery_id '{battery_id}'.")
    bat = batteries[battery_id]
    out.update(
        {
            "battery_capacity_kwh": bat["battery_capacity_kwh"],
            "battery_max_power_kw": bat["battery_max_power_kw"],
            "battery_efficiency": bat["battery_efficiency"],
            "battery_min_soc": bat["battery_min_soc"],
            "battery_max_soc": bat["battery_max_soc"],
            "threshold_power": bat["threshold_power"],
        }
    )
    return out


def resolve_pv_into_settings(settings: dict, pv_systems: dict[str, dict]) -> dict:
    """Ersetzt pv_system_id durch flache PV-Felder (falls gesetzt)."""
    out = dict(settings)
    pv_id = out.pop("pv_system_id", None)
    if not pv_id:
        return out
    pv_id = str(pv_id).strip()
    if pv_id not in pv_systems:
        raise ValueError(f"Unbekannte pv_system_id '{pv_id}'.")
    pv = pv_systems[pv_id]
    out.update(
        {
            "pv_kwp": pv["pv_kwp"],
            "pv_tilt": pv["pv_tilt"],
            "pv_azimuth": pv["pv_azimuth"],
        }
    )
    return out
