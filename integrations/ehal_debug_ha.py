"""HA / OpenEMS mapping helpers for the EHAL Live tables (split from ``ehal_debug_mapping``).

Names stay importable from ``integrations.ehal_debug_mapping``; helpers that still live
there (consumer/battery enumeration, field canonicalisation) are resolved at call time.
"""
from __future__ import annotations

from typing import Any

from ehal.field_catalog import SETPOINT_FIELDS
from integrations.ehal_debug_fields import (
    _MAPPING_DERIVED,
    EV_LIVE_READ_FIELDS,
    EV_LIVE_WRITE_FIELDS,
)


def _m():
    from integrations import ehal_debug_mapping

    return ehal_debug_mapping


def ha_telemetry_mapping(entities: dict[str, str] | None) -> dict[str, str]:
    """EHAL field → HA entity_id (or derived / empty)."""
    ents = entities if isinstance(entities, dict) else {}
    out: dict[str, str] = {}
    for field, entity_id in ents.items():
        name = str(entity_id or "").strip()
        if name:
            out[str(field)] = name
    return out


def openems_telemetry_mapping(
    *,
    ess_component: str = "ess0",
    evcs_component: str = "evcs0",
) -> dict[str, str]:
    """Canonical OpenEMS channel labels for Live-Lesen Mapping column."""
    ess = str(ess_component or "ess0").strip() or "ess0"
    evcs = str(evcs_component or "evcs0").strip() or "evcs0"
    return {
        "sens_grid_power_active": "_sum/GridActivePower",
        "sens_pv_production_active": "_sum/ProductionActivePower",
        "sens_ess_power": f"{ess}/ActivePower",
        "sens_evcs_active_power": f"{evcs}/ActivePower",
        "sens_power_consumers": _MAPPING_DERIVED,
    }


def openems_setpoint_mapping(
    *,
    ess_component: str = "ess0",
    evcs_component: str = "evcs0",
) -> dict[str, str]:
    ess = str(ess_component or "ess0").strip() or "ess0"
    evcs = str(evcs_component or "evcs0").strip() or "evcs0"
    return {
        "set_ess_active_power": f"{ess}/SetActivePowerEquals",
        "set_ess_charge_power_limit": f"{ess}/SetActivePowerGreaterOrEquals",
        "set_ess_discharge_power_limit": f"{ess}/SetActivePowerLessOrEquals",
        "set_evcs_max_current": f"{evcs}/SetChargePowerLimit",
    }


def ha_setpoint_mapping(entities: dict[str, str] | None) -> dict[str, str]:
    ents = entities if isinstance(entities, dict) else {}
    out: dict[str, str] = {}
    for field in SETPOINT_FIELDS:
        entity_id = str(ents.get(field) or "").strip()
        if entity_id:
            out[field] = entity_id
    return out


def _binding_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): str(v).strip()
        for k, v in raw.items()
        if str(v or "").strip()
    }


def _consumers_from_house_doc(house_doc: dict) -> list[dict]:
    """All consumers across profiles in a house_profiles document."""
    profiles = house_doc.get("profiles")
    out: list[dict] = []
    if isinstance(profiles, dict):
        iterable = profiles.values()
    elif isinstance(profiles, list):
        iterable = profiles
    else:
        return out
    for profile in iterable:
        if not isinstance(profile, dict):
            continue
        for consumer in profile.get("consumers") or []:
            if isinstance(consumer, dict):
                out.append(consumer)
    return out


def _ha_live_consumers(house_doc: dict | None) -> list[dict]:
    """Live consumers with house bindings; house_doc-only when ids do not overlap."""
    live: list[dict] = []
    try:
        live = _m()._all_live_consumers()
    except Exception:
        live = []
    if house_doc is None:
        return live
    house_consumers = _consumers_from_house_doc(house_doc)
    if not live:
        return house_consumers
    by_id = {
        str(c.get("id") or "").strip(): c
        for c in house_consumers
        if str(c.get("id") or "").strip()
    }
    live_ids = {str(c.get("id") or "").strip() for c in live if str(c.get("id") or "").strip()}
    if by_id and not (live_ids & set(by_id)):
        # Unit tests / fixtures whose consumer ids differ from ambient Live profile.
        return house_consumers
    return [by_id.get(str(c.get("id") or "").strip()) or c for c in live]


def ha_entity_scoped_live_mapping(house_doc: dict | None = None) -> dict[str, str]:
    """Entity-centric EHAL-Feld → HA entity_id (exchange IDs for Live tables)."""
    if house_doc is None:
        from ui.house_config_io import load_house_profiles

        house_doc = load_house_profiles()
    from ehal.qualified_ids import qualified_plant_id

    out: dict[str, str] = {}
    plant = house_doc.get("plant") if isinstance(house_doc.get("plant"), dict) else {}
    for field, entity_id in _binding_map(plant.get("ehal_bindings")).items():
        if _m().is_live_read_field(field):
            out[qualified_plant_id(field)] = entity_id
        else:
            out[qualified_plant_id(field)] = entity_id
    for consumer in _ha_live_consumers(house_doc):
        if not str(consumer.get("id") or "").strip():
            continue
        for field, entity_id in _binding_map(consumer.get("ehal_bindings")).items():
            if _m().is_live_read_field(field):
                out[_m().live_read_consumer_field(consumer, field)] = entity_id
            else:
                out[_m().live_write_consumer_field(consumer, field)] = entity_id
    for inverter in _m()._all_live_inverters():
        bindings = inverter.get("ehal_bindings")
        if not isinstance(bindings, dict):
            continue
        for field, entity_id in _binding_map(bindings).items():
            out[str(field)] = entity_id
    for pv in _m()._all_live_pv_systems():
        bindings = pv.get("ehal_bindings")
        if not isinstance(bindings, dict):
            continue
        for field, entity_id in _binding_map(bindings).items():
            out[str(field)] = entity_id
    return out


def expand_ha_telemetry_for_live(
    telemetry: dict[str, Any],
    house_doc: dict | None = None,
) -> dict[str, Any]:
    """Alias flat HA wire keys onto qualified Live-Lesen IDs; drop bare EV/grid keys."""
    from ehal.qualified_ids import GRID_KINDS, field_kind, qualified_plant_id

    flat = {str(k): v for k, v in telemetry.items()}
    out: dict[str, Any] = dict(flat)
    for name, value in list(flat.items()):
        kind = field_kind(name)
        if kind in GRID_KINDS:
            out[qualified_plant_id(kind)] = value
            if name != qualified_plant_id(kind):
                out.pop(name, None)
    for consumer in _ha_live_consumers(house_doc):
        cid = str(consumer.get("id") or "").strip()
        if not cid or not _m()._consumer_is_ev(consumer):
            continue
        for name in EV_LIVE_READ_FIELDS:
            if name in flat:
                out[_m().live_read_consumer_field(consumer, name)] = flat[name]
    for name in EV_LIVE_READ_FIELDS:
        out.pop(name, None)
    return out


def expand_ha_writes_for_live(
    writes: list[dict[str, Any]],
    house_doc: dict | None = None,
) -> list[dict[str, Any]]:
    """Rewrite flat EV setpoint field ids to qualified Live-Schreiben IDs."""
    ev_consumer: dict | None = None
    for consumer in _ha_live_consumers(house_doc):
        if str(consumer.get("id") or "").strip() and _m()._consumer_is_ev(consumer):
            ev_consumer = consumer
            break
    out: list[dict[str, Any]] = []
    for entry in writes:
        row = dict(entry)
        field = str(row.get("field") or "").strip()
        if ev_consumer is not None and field in EV_LIVE_WRITE_FIELDS:
            row["field"] = _m().live_write_consumer_field(ev_consumer, field)
        else:
            canon = _m().canonicalize_live_display_field(field)
            if canon:
                row["field"] = canon
        out.append(row)
    return out
