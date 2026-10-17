"""Battery entity normalization (split from entity_resolution)."""
from __future__ import annotations

from house_config.battery_control import (
    normalize_battery_control,
)
from house_config.powerstation import (
    BATTERY_TYPE_HOUSE,
    BATTERY_TYPE_POWERSTATION,
    is_virtual_powerstation,
    normalize_battery_type,
    normalize_powerstation_fields,
)


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


def _resolve_battery_regulates_on(
    raw: dict, bat_type: str, *, battery_id: str, index: int
) -> str | None:
    """``regulates_on`` for house batteries; forbidden on Powerstations."""
    from house_config.topology_regulates import normalize_regulates_on

    if bat_type == BATTERY_TYPE_POWERSTATION and "regulates_on" in raw:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): regulates_on ist nur für "
            "type=house erlaubt (Powerstations weglassen)."
        )
    if bat_type != BATTERY_TYPE_HOUSE:
        return None
    return normalize_regulates_on(
        raw.get("regulates_on"),
        entity_kind="batteries",
        entity_id=battery_id,
        index=index,
        required=True,
    )


def _validated_battery_discharge_kw(
    bat_type: str,
    capacity: float,
    charge_kw: float,
    discharge_kw: float,
    *,
    battery_id: str,
    index: int,
) -> float:
    """Check charge/discharge limits against capacity; return the effective discharge kW."""
    if bat_type == BATTERY_TYPE_POWERSTATION:
        if capacity > 0.0 and charge_kw <= 0.0:
            raise ValueError(
                f"batteries[{index}] ('{battery_id}'): "
                "powerstation battery_max_charge_power_kw muss > 0 sein."
            )
        # Physical one-way packs cannot feed the house grid; discharge may be 0.
        return max(0.0, discharge_kw)
    if capacity > 0.0 and (charge_kw <= 0.0 or discharge_kw <= 0.0):
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): "
            "battery_max_charge/discharge_power_kw muss > 0 sein."
        )
    return discharge_kw


def _raw_battery_ehal_bindings(raw: dict, *, battery_id: str, index: int) -> dict:
    ehal_bindings = raw.get("ehal_bindings")
    if ehal_bindings is None:
        ehal_bindings = {}
    if not isinstance(ehal_bindings, dict):
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): ehal_bindings muss ein Objekt sein."
        )
    return ehal_bindings


def _apply_battery_inverter_id(
    out: dict, inverter_id: str, *, battery_id: str, index: int
) -> None:
    """Virtual Powerstations carry no inverter_id; every other battery requires one."""
    if is_virtual_powerstation(out):
        if inverter_id:
            raise ValueError(
                f"batteries[{index}] ('{battery_id}'): virtuelle Powerstation "
                "darf keinen inverter_id haben."
            )
    elif inverter_id:
        out["inverter_id"] = inverter_id
    else:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): inverter_id fehlt."
        )


def _validated_threshold_and_standby(
    raw: dict, *, battery_id: str, index: int
) -> tuple[float, float]:
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
    if "kind" in raw:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): field 'kind' is removed (2.7.l). "
            "Use inverters[].ac_connection; run "
            "python -m scripts.migrate_inverters_once --config-dir <config-dir>"
        )
    return threshold, standby


def _apply_battery_id_lock_fields(out: dict, raw: dict) -> None:
    if "id_locked" in raw:
        out["id_locked"] = bool(raw.get("id_locked"))
    provisional = str(raw.get("id_provisional_label") or "").strip()
    if provisional and not out.get("id_locked", True):
        out["id_provisional_label"] = provisional


def normalize_battery(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"batteries[{index}] muss ein Objekt sein.")
    battery_id = str(raw.get("id", "")).strip()
    if not battery_id:
        raise ValueError(f"batteries[{index}]: id fehlt.")
    label = str(raw.get("label", battery_id)).strip() or battery_id
    threshold, standby = _validated_threshold_and_standby(
        raw, battery_id=battery_id, index=index
    )
    control = normalize_battery_control(
        raw.get("control"), battery_id=battery_id, index=index
    )
    charge_kw, discharge_kw = split_battery_max_power_kw(
        raw, battery_id=battery_id, index=index
    )
    bat_type = normalize_battery_type(
        raw.get("type"), battery_id=battery_id, index=index
    )
    regulates_on = _resolve_battery_regulates_on(
        raw, bat_type, battery_id=battery_id, index=index
    )
    capacity = float(raw["battery_capacity_kwh"])
    discharge_kw = _validated_battery_discharge_kw(
        bat_type, capacity, charge_kw, discharge_kw, battery_id=battery_id, index=index
    )
    ehal_bindings = _raw_battery_ehal_bindings(raw, battery_id=battery_id, index=index)
    inverter_id = str(raw.get("inverter_id") or "").strip()
    out = {
        "id": battery_id,
        "label": label,
        "type": bat_type,
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
        # Q8: empty string values are Loxone activation flags — keep the keys
        # (same as components_store). Stripping empties breaks PS writes via
        # _planning_powerstations → _binding_for_ps.
        "ehal_bindings": {
            str(k): str(v).strip()
            for k, v in ehal_bindings.items()
            if str(k or "").strip()
        },
        "battery_wear": _normalize_battery_wear(raw.get("battery_wear"), battery_id, index),
    }
    if regulates_on is not None:
        out["regulates_on"] = regulates_on
    if bat_type == BATTERY_TYPE_POWERSTATION:
        out.update(
            normalize_powerstation_fields(raw, battery_id=battery_id, index=index)
        )
    _apply_battery_inverter_id(out, inverter_id, battery_id=battery_id, index=index)
    _apply_battery_id_lock_fields(out, raw)
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
