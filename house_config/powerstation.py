"""Powerstation entity helpers (2.7.g / 2.7.h shared model)."""
from __future__ import annotations

from typing import Any

from house_config.battery_kind import DEFAULT_BATTERY_KIND

BATTERY_TYPE_HOUSE = "house"
BATTERY_TYPE_POWERSTATION = "powerstation"

BACKING_VIRTUAL = "virtual"
BACKING_PHYSICAL = "physical"

ROLE_SINGLE_USE = "single_use"
ROLE_STANDBY_BACKUP = "standby_backup"

MODE_ADVICE = "advice"
MODE_RESERVE = "reserve"

# Virtual carve-out: not a setpoint-capable ESS unit (UI-hidden).
VIRTUAL_PS_CONTROL = "limits_only"

_VALID_TYPES = frozenset({BATTERY_TYPE_HOUSE, BATTERY_TYPE_POWERSTATION})
_VALID_BACKINGS = frozenset({BACKING_VIRTUAL, BACKING_PHYSICAL})
_VALID_ROLES = frozenset({ROLE_SINGLE_USE, ROLE_STANDBY_BACKUP})
_VALID_MODES = frozenset({MODE_ADVICE, MODE_RESERVE})


def normalize_battery_type(raw: object, *, battery_id: str, index: int) -> str:
    if raw is None or raw == "":
        return BATTERY_TYPE_HOUSE
    value = str(raw).strip().lower()
    if value not in _VALID_TYPES:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): type muss "
            f"'house' oder 'powerstation' sein (erhalten: {raw!r})."
        )
    return value


def is_powerstation(battery: dict) -> bool:
    return str(battery.get("type") or BATTERY_TYPE_HOUSE).strip().lower() == (
        BATTERY_TYPE_POWERSTATION
    )


def is_house_battery(battery: dict) -> bool:
    return not is_powerstation(battery)


def is_virtual_powerstation(battery: dict) -> bool:
    if not is_powerstation(battery):
        return False
    backing = str(battery.get("backing") or BACKING_VIRTUAL).strip().lower()
    return backing == BACKING_VIRTUAL


def primary_house_battery(
    batteries: list[dict] | None,
    *,
    exclude_id: str = "",
) -> dict | None:
    """First ``type=house`` battery (primary ESS for virtual carve-out)."""
    skip = str(exclude_id or "").strip()
    for item in batteries or []:
        if not isinstance(item, dict):
            continue
        bid = str(item.get("id") or "").strip()
        if skip and bid == skip:
            continue
        if is_house_battery(item):
            return item
    return None


def _charge_kw_from_house(house: dict) -> float:
    raw = house.get("battery_max_charge_power_kw")
    if raw is not None:
        try:
            value = float(raw)
            if value > 0.0:
                return value
        except (TypeError, ValueError):
            pass
    legacy = house.get("battery_max_power_kw")
    if legacy is not None:
        try:
            value = float(legacy)
            if value > 0.0:
                return value
        except (TypeError, ValueError):
            pass
    capacity = float(house.get("battery_capacity_kwh") or 0.0)
    return max(0.1, capacity * 0.5) if capacity > 0.0 else 1.0


def virtual_powerstation_fill_fields(
    *,
    primary_house: dict | None,
    capacity_kwh: float,
) -> dict[str, Any]:
    """Hidden electrical fields for a virtual powerstation (inherit or defaults)."""
    fixed = {
        "battery_max_discharge_power_kw": 0.0,
        "standby_power_kw": 0.0,
        "limits_from_live": False,
        "kind": DEFAULT_BATTERY_KIND,
        "control": VIRTUAL_PS_CONTROL,
        "battery_wear": {"enabled": False},
    }
    if primary_house is not None:
        return {
            **fixed,
            "battery_max_charge_power_kw": _charge_kw_from_house(primary_house),
            "battery_efficiency": float(primary_house.get("battery_efficiency") or 0.95),
            "battery_min_soc": float(primary_house.get("battery_min_soc") or 0.0),
            "battery_max_soc": float(primary_house.get("battery_max_soc") or 100.0),
            "threshold_power": float(primary_house.get("threshold_power") or 0.05),
        }
    cap = float(capacity_kwh or 0.0)
    charge = max(0.1, cap * 0.5) if cap > 0.0 else 1.0
    return {
        **fixed,
        "battery_max_charge_power_kw": charge,
        "battery_efficiency": 0.95,
        "battery_min_soc": 0.0,
        "battery_max_soc": 100.0,
        "threshold_power": 0.05,
    }


def apply_virtual_powerstation_inheritance(
    raw: dict,
    batteries: list[dict] | None,
) -> dict:
    """Overwrite UI-hidden fields on virtual powerstations; pass-through otherwise."""
    if not isinstance(raw, dict) or not is_virtual_powerstation(raw):
        return raw
    out = dict(raw)
    primary = primary_house_battery(
        batteries,
        exclude_id=str(out.get("id") or ""),
    )
    capacity = float(out.get("battery_capacity_kwh") or 0.0)
    out.update(
        virtual_powerstation_fill_fields(
            primary_house=primary,
            capacity_kwh=capacity,
        )
    )
    return out


def normalize_attached_consumer_ids(raw: dict) -> list[str]:
    """Merge ``attached_consumer_ids`` + legacy singular ``attached_consumer_id``."""
    ids: list[str] = []
    seen: set[str] = set()
    raw_list = raw.get("attached_consumer_ids")
    if isinstance(raw_list, list):
        for item in raw_list:
            cid = str(item or "").strip()
            if cid and cid not in seen:
                ids.append(cid)
                seen.add(cid)
    singular = str(raw.get("attached_consumer_id") or "").strip()
    if singular and singular not in seen:
        ids.append(singular)
    return ids


def normalize_powerstation_fields(
    raw: dict,
    *,
    battery_id: str,
    index: int,
) -> dict:
    """Return backing / role / attached consumer ids for type=powerstation."""
    backing = str(raw.get("backing") or BACKING_VIRTUAL).strip().lower()
    if backing not in _VALID_BACKINGS:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): backing muss "
            f"'virtual' oder 'physical' sein (erhalten: {raw.get('backing')!r})."
        )
    role = str(raw.get("role") or ROLE_SINGLE_USE).strip().lower()
    if role not in _VALID_ROLES:
        raise ValueError(
            f"batteries[{index}] ('{battery_id}'): role muss "
            f"'single_use' oder 'standby_backup' sein (erhalten: {raw.get('role')!r})."
        )
    # Optional at create time — link may be completed later via Verbraucher
    # Unterstützung „Energiereserve“ (powerstation_id → attached_consumer_ids sync).
    attached_ids = normalize_attached_consumer_ids(raw)
    # Physical one-way packs stay 1:1; keep first id if several were stored.
    if backing == BACKING_PHYSICAL and len(attached_ids) > 1:
        attached_ids = attached_ids[:1]
    return {
        "backing": backing,
        "role": role,
        "attached_consumer_ids": attached_ids,
        "attached_consumer_id": attached_ids[0] if attached_ids else "",
    }


def reserve_links_from_consumers(consumers: list[dict]) -> dict[str, list[str]]:
    """Map powerstation_id → attached consumer ids from reserve-mode manuals."""
    links: dict[str, list[str]] = {}
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        if consumer_assist_mode(consumer) != MODE_RESERVE:
            continue
        ps_id = consumer_powerstation_id(consumer)
        cid = str(consumer.get("id") or "").strip()
        if not ps_id or not cid:
            continue
        bucket = links.setdefault(ps_id, [])
        if cid not in bucket:
            bucket.append(cid)
    return links


def normalize_assist_mode(raw: object) -> str:
    if raw is None or raw == "":
        return MODE_ADVICE
    value = str(raw).strip().lower()
    if value not in _VALID_MODES:
        raise ValueError(
            f"appliance_recommendation.mode muss 'advice' oder 'reserve' sein "
            f"(erhalten: {raw!r})."
        )
    return value


def consumer_assist_mode(consumer: dict) -> str:
    rec = consumer.get("appliance_recommendation")
    if not isinstance(rec, dict):
        return MODE_ADVICE
    return normalize_assist_mode(rec.get("mode"))


def consumer_powerstation_id(consumer: dict) -> str:
    rec = consumer.get("appliance_recommendation")
    if not isinstance(rec, dict):
        return ""
    return str(rec.get("powerstation_id") or "").strip()


def is_reserve_mode(consumer: dict) -> bool:
    return consumer_assist_mode(consumer) == MODE_RESERVE


def is_advice_mode(consumer: dict) -> bool:
    return consumer_assist_mode(consumer) == MODE_ADVICE


def powerstations_by_id(batteries: dict[str, dict]) -> dict[str, dict]:
    return {bid: bat for bid, bat in batteries.items() if is_powerstation(bat)}


def house_batteries_by_id(batteries: dict[str, dict]) -> dict[str, dict]:
    return {bid: bat for bid, bat in batteries.items() if is_house_battery(bat)}
