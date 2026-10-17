"""Auflösung von batteries[], pv_systems[] und inverters[] in runtime_settings."""
from __future__ import annotations

from house_config.battery_control import (
    DEFAULT_BATTERY_CONTROL,
)
from house_config.inverter import (
    AC_GRID_TIED,
    DEFAULT_AC_CONNECTION,
    inverters_by_id,
    planning_inverter_entry,
    reject_if_needs_conversion_efficiency_migration,
    validate_inverter_topology,
)
from house_config.powerstation import (
    BATTERY_TYPE_HOUSE,
    is_powerstation,
    is_virtual_powerstation,
    primary_house_battery,
)
from house_config.battery_normalize import (  # noqa: F401  (re-exported)
    _normalize_battery_wear,
    battery_wear_cent_per_kwh,
    normalize_battery,
    split_battery_max_power_kw,
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
    "battery_ac_connection": DEFAULT_AC_CONNECTION,
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
        "_planning_inverters",
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
    entry = {
        "id": pv["id"],
        "label": pv["label"],
        "pv_kwp": float(pv["pv_kwp"]),
        "pv_tilt": float(pv["pv_tilt"]),
        "pv_azimuth": float(pv["pv_azimuth"]),
    }
    inv_id = str(pv.get("inverter_id") or "").strip()
    if inv_id:
        entry["inverter_id"] = inv_id
    return entry










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
    inverter_id = str(raw.get("inverter_id") or "").strip()
    if not inverter_id:
        raise ValueError(f"pv_systems[{index}] ('{pv_id}'): inverter_id fehlt.")
    ehal_bindings = raw.get("ehal_bindings")
    if ehal_bindings is None:
        ehal_bindings = {}
    if not isinstance(ehal_bindings, dict):
        raise ValueError(
            f"pv_systems[{index}] ('{pv_id}'): ehal_bindings muss ein Objekt sein."
        )
    out = {
        "id": pv_id,
        "label": label,
        "pv_kwp": kwp,
        "pv_tilt": float(raw.get("pv_tilt", raw.get("tilt", 0.0))),
        "pv_azimuth": float(raw.get("pv_azimuth", raw.get("azimuth", 0.0))),
        "inverter_id": inverter_id,
        "ehal_bindings": {
            str(k): str(v).strip()
            for k, v in ehal_bindings.items()
            if str(k or "").strip()
        },
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
        "ac_connection": str(
            bat.get("ac_connection") or DEFAULT_AC_CONNECTION
        ).strip().lower()
        or DEFAULT_AC_CONNECTION,
        "ehal_bindings": dict(bat.get("ehal_bindings") or {}),
        "battery_wear": (
            dict(bat["battery_wear"]) if bat.get("battery_wear") is not None else None
        ),
    }
    if bat.get("regulates_on") is not None:
        entry["regulates_on"] = bat["regulates_on"]
    inv_id = str(bat.get("inverter_id") or "").strip()
    if inv_id:
        entry["inverter_id"] = inv_id
    if is_powerstation(bat):
        entry["backing"] = bat["backing"]
        entry["role"] = bat["role"]
        entry["attached_consumer_ids"] = list(bat.get("attached_consumer_ids") or [])
        entry["attached_consumer_id"] = bat.get("attached_consumer_id") or (
            entry["attached_consumer_ids"][0] if entry["attached_consumer_ids"] else ""
        )
    return entry


def _path_efficiency_from_planning(entry: dict) -> float:
    """η_path = η_inv · η_batt for MILP/sim SoC (fail loud if η_inv missing)."""
    bat_id = entry.get("id", "?")
    eta_batt = float(entry["battery_efficiency"])
    if "inverter_efficiency" not in entry:
        raise ValueError(
            f"Batterie '{bat_id}': inverter_efficiency (η_inv) fehlt auf "
            "Planning-Eintrag — components.json migrieren?"
        )
    eta_inv = float(entry["inverter_efficiency"])
    if not (0.0 < eta_inv <= 1.0):
        raise ValueError(
            f"Batterie '{bat_id}': inverter_efficiency muss in (0, 1] liegen "
            f"(got {eta_inv!r})."
        )
    if not (0.0 < eta_batt <= 1.0):
        raise ValueError(
            f"Batterie '{bat_id}': battery_efficiency muss in (0, 1] liegen "
            f"(got {eta_batt!r})."
        )
    return eta_inv * eta_batt


def battery_params_from_planning(entry: dict) -> dict:
    """Optimizer-shaped params dict from a planning battery entry."""
    bat_id = entry["id"]
    out = {
        "id": bat_id,
        "label": str(entry.get("label") or bat_id).strip() or bat_id,
        "type": entry.get("type", BATTERY_TYPE_HOUSE),
        "ac_connection": str(
            entry.get("ac_connection") or DEFAULT_AC_CONNECTION
        ).strip().lower()
        or DEFAULT_AC_CONNECTION,
        "battery_capacity_kwh": float(entry["battery_capacity_kwh"]),
        "min_soc": float(entry["battery_min_soc"]),
        "max_soc": float(entry["battery_max_soc"]),
        "max_charge_power_kw": float(entry["battery_max_charge_power_kw"]),
        "max_discharge_power_kw": float(entry["battery_max_discharge_power_kw"]),
        "max_power_kw": float(entry["battery_max_power_kw"]),
        "efficiency": _path_efficiency_from_planning(entry),
        "standby_power_kw": float(entry.get("standby_power_kw", 0.0) or 0.0),
        "threshold_power": float(entry.get("threshold_power", 0.02) or 0.02),
        "control": str(entry.get("control", DEFAULT_BATTERY_CONTROL) or DEFAULT_BATTERY_CONTROL),
        "limits_from_live": bool(entry.get("limits_from_live", False)),
        "ehal_bindings": dict(entry.get("ehal_bindings") or {}),
    }
    inv_id = str(entry.get("inverter_id") or "").strip()
    if inv_id:
        out["inverter_id"] = inv_id
    if is_powerstation(entry):
        out["backing"] = entry.get("backing")
        out["role"] = entry.get("role")
        attached_ids = list(entry.get("attached_consumer_ids") or [])
        out["attached_consumer_ids"] = attached_ids
        out["attached_consumer_id"] = entry.get("attached_consumer_id") or (
            next(iter(attached_ids), "")
        )
    return out


def _select_planning_batteries(
    bat_ids: list[str], batteries: dict[str, dict]
) -> list[dict]:
    """Planning entries of the selected house batteries (powerstations soft-skipped)."""
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
    return planning


def _flat_battery_fields(planning: list[dict]) -> dict:
    """Flat singular battery fields from the first selected battery (+ summed standby)."""
    first = planning[0]
    return {
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
        "battery_ac_connection": first.get(
            "ac_connection", DEFAULT_AC_CONNECTION
        ),
        "limits_from_live": bool(first.get("limits_from_live", False)),
    }


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

    planning = _select_planning_batteries(bat_ids, batteries)
    if not planning:
        out["_planning_batteries"] = []
        if "battery_capacity_kwh" not in out:
            out.update(ZERO_BATTERY_FLAT)
        return out

    out["_planning_batteries"] = planning
    first = planning[0]
    out.update(_flat_battery_fields(planning))
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


def attach_ac_connection_from_inverters(
    batteries: dict[str, dict],
    inverters: dict[str, dict],
) -> None:
    """Mutate batteries in place: copy inverter ac_connection onto each battery."""
    for bat in batteries.values():
        if is_virtual_powerstation(bat):
            bat["ac_connection"] = AC_GRID_TIED
            continue
        inv_id = str(bat.get("inverter_id") or "").strip()
        inv = inverters.get(inv_id) if inv_id else None
        if inv is None:
            bat["ac_connection"] = DEFAULT_AC_CONNECTION
        else:
            bat["ac_connection"] = inv["ac_connection"]


def _eta_inv_for_planning_entry(
    entry: dict,
    *,
    inverters: dict[str, dict],
    batteries: dict[str, dict],
) -> float:
    """Resolve η_inv for a planning battery / powerstation entry."""
    bat_id = entry.get("id", "?")
    if is_virtual_powerstation(entry):
        primary = primary_house_battery(list(batteries.values()))
        if primary is None:
            raise ValueError(
                f"Batterie '{bat_id}': virtuelle Powerstation ohne Hausbatterie "
                "— η_inv nicht ableitbar."
            )
        inv_id = str(primary.get("inverter_id") or "").strip()
    else:
        inv_id = str(entry.get("inverter_id") or "").strip()
    if not inv_id:
        raise ValueError(
            f"Batterie '{bat_id}': inverter_id fehlt für η_inv."
        )
    inv = inverters.get(inv_id)
    if inv is None:
        raise ValueError(
            f"Batterie '{bat_id}': unbekannte inverter_id '{inv_id}'."
        )
    if "efficiency" not in inv:
        raise ValueError(
            f"Inverter '{inv_id}': efficiency (η_inv) fehlt."
        )
    return float(inv["efficiency"])


def attach_inverter_efficiency_to_planning(
    settings: dict,
    *,
    inverters: dict[str, dict],
    batteries: dict[str, dict],
) -> None:
    """Mutate planning entries: set inverter_efficiency (η_inv) for η_path."""
    for key in ("_planning_batteries", "_planning_powerstations"):
        for entry in settings.get(key) or []:
            if not isinstance(entry, dict):
                continue
            entry["inverter_efficiency"] = _eta_inv_for_planning_entry(
                entry, inverters=inverters, batteries=batteries
            )


def resolve_inverters_into_settings(
    settings: dict,
    *,
    inverters: dict[str, dict],
    batteries: dict[str, dict],
    pv_systems: dict[str, dict],
) -> dict:
    """Inject ``_planning_inverters`` for inverters referenced by selected assets."""
    out = dict(settings)
    inv_ids: list[str] = []
    for bat in out.get("_planning_batteries") or []:
        inv_id = str(bat.get("inverter_id") or "").strip()
        if inv_id and inv_id not in inv_ids:
            inv_ids.append(inv_id)
    for bat in out.get("_planning_powerstations") or []:
        inv_id = str(bat.get("inverter_id") or "").strip()
        if inv_id and inv_id not in inv_ids:
            inv_ids.append(inv_id)
    for pv in out.get("_planning_pv_systems") or []:
        inv_id = str(pv.get("inverter_id") or "").strip()
        if inv_id and inv_id not in inv_ids:
            inv_ids.append(inv_id)
    planning: list[dict] = []
    for inv_id in inv_ids:
        if inv_id not in inverters:
            raise ValueError(f"Unbekannte inverter_id '{inv_id}'.")
        planning.append(planning_inverter_entry(inverters[inv_id]))
    out["_planning_inverters"] = planning
    # Keep full catalogs available for topology validation callers.
    _ = batteries, pv_systems
    return out


def resolve_components_into_settings(
    settings: dict,
    components: dict,
) -> dict:
    """Normalize components, validate topology, resolve batteries/PV/inverters."""
    from house_config.inverter import reject_if_needs_inverter_migration
    from house_config.migrate_topology import reject_if_needs_topology_migration

    reject_if_needs_inverter_migration(components)
    reject_if_needs_conversion_efficiency_migration(components)
    reject_if_needs_topology_migration(components)
    inverters = inverters_by_id(components)
    batteries = batteries_by_id(components)
    pv_systems = pv_systems_by_id(components)
    validate_inverter_topology(
        inverters=inverters, batteries=batteries, pv_systems=pv_systems
    )
    attach_ac_connection_from_inverters(batteries, inverters)
    out = resolve_battery_into_settings(settings, batteries)
    out = resolve_pv_into_settings(out, pv_systems)
    attach_inverter_efficiency_to_planning(
        out, inverters=inverters, batteries=batteries
    )
    return resolve_inverters_into_settings(
        out, inverters=inverters, batteries=batteries, pv_systems=pv_systems
    )
