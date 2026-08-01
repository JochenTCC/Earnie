"""EHAL Live-Lesen / Live-Schreiben table helpers (field ↔ backend Mapping)."""
from __future__ import annotations

from typing import Any, Sequence

from integrations.loxone_ehal_mapping import (
    SETPOINT_FIELDS,
    TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
)

# Unmapped Mapping cells stay empty (not an em-dash).
_MAPPING_EMPTY = ""
_MAPPING_DERIVED = "—(abgeleitet)"

PLANT_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_grid_power_active",
    "sens_pv_production_active",
    "sens_ess_soc",
    "sens_ess_power",
    "sens_power_consumers",
)

PLANT_LIVE_WRITE_FIELDS: tuple[str, ...] = (
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_mode",
)

EV_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_evcs_active_power",
    "sens_evcs_connected",
    "sens_evcs_soc_act",
    "get_evcs_nominal_current",
    "sens_evcs_bat_capacity",
    "get_evcs_ready_by_time",
    "get_evcs_limit_soc",
)

EV_LIVE_WRITE_FIELDS: tuple[str, ...] = (
    "set_evcs_max_current",
    "set_evcs_mode",
)

FILTER_LIVE_READ_FIELDS: tuple[str, ...] = (
    "get_filter_remaining_hours",
    "sens_filter_active",
    "get_filter_native_start_hour",
    "get_filter_native_duration_hours",
)

NETWORK_LIVE_READ_FIELDS: tuple[str, ...] = TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL
NETWORK_LIVE_WRITE_FIELDS: tuple[str, ...] = SETPOINT_FIELDS


def is_live_read_field(field: str) -> bool:
    """True for Live-Lesen rows (``sens_*`` / ``get_*`` / flex ``*.sens_power_act``)."""
    from ehal.flex_fields import is_flex_live_read_field

    name = str(field or "").strip()
    if ":" in name:
        name = name.split(":", 1)[1]
    return (
        name.startswith("sens_")
        or name.startswith("get_")
        or is_flex_live_read_field(name)
    )


def is_live_write_field(field: str) -> bool:
    """True for Live-Schreiben rows (``set_*`` / flex ``set_enable`` / setpoint)."""
    from ehal.flex_fields import KIND_SET_ENABLE, KIND_SET_POWER_SETPOINT, flex_field_kind

    name = str(field or "").strip()
    if ":" in name:
        name = name.split(":", 1)[1]
    if name.startswith("set_"):
        return True
    kind = flex_field_kind(name)
    return kind in (KIND_SET_ENABLE, KIND_SET_POWER_SETPOINT)


def _consumer_is_ev(consumer: dict) -> bool:
    if str(consumer.get("type") or "") == "ev":
        return True
    sched = consumer.get("charging_schedule") or {}
    if isinstance(sched, dict) and sched.get("enabled"):
        return True
    return False


def _consumer_is_filter(consumer: dict) -> bool:
    cid = str(consumer.get("id") or "").strip().lower()
    if cid in ("swimspa_filter", "pool_filter"):
        return True
    return consumer.get("daily_target_source") == "loxone_remaining_hours"


def _has_greenfield_pool_filter(by_id: dict[str, dict]) -> bool:
    """True when house profile already has greenfield ``pool_filter`` (not bridge-only)."""
    if "pool_filter" in by_id:
        return True
    for cid, consumer in by_id.items():
        if str(cid).strip().lower() == "swimspa_filter":
            continue
        if not isinstance(consumer, dict):
            continue
        from settings.ehal_marker_resolve import marker_flex_enable

        if str(marker_flex_enable(consumer) or "").strip() == "Earnie_Pool_Filter_Freigabe":
            return True
    return False


def _all_live_consumers() -> list[dict]:
    """House-profile + flex consumers (including unmapped).

    When greenfield ``pool_filter`` exists, omit bridged ``swimspa_filter`` so Live
    tables do not show two Filter-Freigabe rows.
    """
    import config

    by_id: dict[str, dict] = {}
    resolved = config.CONFIG.get_resolved_runtime_settings()
    profile = resolved.get("_house_profile") if isinstance(resolved, dict) else None
    if isinstance(profile, dict):
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict):
                continue
            cid = str(consumer.get("id") or "").strip()
            if cid:
                by_id[cid] = consumer
    for consumer in config.get_flexible_consumers():
        if not isinstance(consumer, dict):
            continue
        cid = str(consumer.get("id") or "").strip()
        if cid and cid not in by_id:
            by_id[cid] = consumer
    if _has_greenfield_pool_filter(by_id):
        by_id.pop("swimspa_filter", None)
    return list(by_id.values())


def expected_live_read_fields(*, network_backend: bool = False) -> list[str]:
    """Canonical Live-Lesen field ids (plant + consumers), including unmapped."""
    if network_backend:
        return list(NETWORK_LIVE_READ_FIELDS)
    fields = list(PLANT_LIVE_READ_FIELDS)
    for consumer in _all_live_consumers():
        cid = str(consumer.get("id") or "").strip()
        if not cid:
            continue
        if _consumer_is_ev(consumer):
            fields.extend(f"{cid}:{name}" for name in EV_LIVE_READ_FIELDS)
        elif _consumer_is_filter(consumer):
            from ehal.flex_fields import flex_sens_power_act

            fields.append(f"{cid}:{flex_sens_power_act(cid)}")
            fields.extend(f"{cid}:{name}" for name in FILTER_LIVE_READ_FIELDS)
        else:
            from ehal.flex_fields import flex_sens_power_act

            fields.append(f"{cid}:{flex_sens_power_act(cid)}")
    return fields


def expected_live_write_fields(*, network_backend: bool = False) -> list[str]:
    """Canonical Live-Schreiben ids (plant + EV + flex Freigabe/Sollwert)."""
    if network_backend:
        return list(NETWORK_LIVE_WRITE_FIELDS)
    from ehal.flex_fields import flex_set_enable, flex_set_power_setpoint
    from settings.ehal_marker_resolve import (
        marker_flex_enable,
        marker_flex_power_setpoint,
    )

    fields = list(PLANT_LIVE_WRITE_FIELDS)
    for consumer in _all_live_consumers():
        cid = str(consumer.get("id") or "").strip()
        if not cid:
            continue
        if _consumer_is_ev(consumer):
            fields.extend(f"{cid}:{name}" for name in EV_LIVE_WRITE_FIELDS)
            continue
        if marker_flex_enable(consumer):
            fields.append(f"{cid}:{flex_set_enable(cid)}")
        if marker_flex_power_setpoint(consumer):
            fields.append(f"{cid}:{flex_set_power_setpoint(cid)}")
    return fields


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
        "sens_ess_soc": f"{ess}/Soc",
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


def mapping_or_dash(mapping: dict[str, str], field: str) -> str:
    value = str(mapping.get(field) or "").strip()
    return value if value else _MAPPING_EMPTY


def build_loxone_setpoint_io_index(*, include_write_aliases: bool = True) -> dict[str, str]:
    """Merker IO-Name → EHAL write field (plant + EV + flex Freigabe/Sollwert)."""
    import config
    from ehal.flex_fields import flex_set_enable, flex_set_power_setpoint
    from settings.ehal_marker_resolve import (
        marker_flex_enable,
        marker_flex_power_setpoint,
        marker_set_evcs_max_current,
        marker_set_evcs_mode,
    )

    index: dict[str, str] = {}
    plant_map = (
        ("set_ess_active_power", "LOXONE_TARGET_ACTIVE_POWER_NAME"),
        ("set_ess_charge_power_limit", "LOXONE_TARGET_CHARGE_POWER_NAME"),
        ("set_ess_discharge_power_limit", "LOXONE_TARGET_DISCHARGE_POWER_NAME"),
        ("set_ess_mode", "LOXONE_CONTROL_CMD_NAME"),
    )
    for field, cfg_key in plant_map:
        io_name = str(config.get(cfg_key) or "").strip()
        if io_name:
            index[io_name] = field

    for consumer in _all_live_consumers():
        cid = str(consumer.get("id") or "").strip()
        if not cid:
            continue
        if _consumer_is_ev(consumer):
            for field, marker in (
                ("set_evcs_max_current", marker_set_evcs_max_current(consumer)),
                ("set_evcs_mode", marker_set_evcs_mode(consumer)),
            ):
                io_name = str(marker or "").strip()
                if io_name:
                    index[io_name] = f"{cid}:{field}"
            continue
        enable = str(marker_flex_enable(consumer) or "").strip()
        if enable:
            index[enable] = f"{cid}:{flex_set_enable(cid)}"
        setpoint = str(marker_flex_power_setpoint(consumer) or "").strip()
        if setpoint:
            index[setpoint] = f"{cid}:{flex_set_power_setpoint(cid)}"

    if not include_write_aliases:
        return index

    # Resolve legacy bridge writes onto the greenfield pool_filter Live row.
    if any(str(c.get("id") or "") == "pool_filter" for c in _all_live_consumers()):
        pool_field = f"pool_filter:{flex_set_enable('pool_filter')}"
        for consumer in config.get_flexible_consumers():
            if str(consumer.get("id") or "") != "swimspa_filter":
                continue
            legacy = str(marker_flex_enable(consumer) or "").strip()
            if legacy and legacy not in index:
                index[legacy] = pool_field
            break
    return index


def loxone_write_field_to_io() -> dict[str, str]:
    """EHAL write field → configured Merker (primary bindings only, no aliases)."""
    return {
        field: io
        for io, field in build_loxone_setpoint_io_index(include_write_aliases=False).items()
    }


def resolve_loxone_write_field(io_name: str, index: dict[str, str] | None = None) -> str:
    """Reverse-map Merker → EHAL write field (or empty if unknown / not a write)."""
    name = str(io_name or "").strip()
    if not name:
        return _MAPPING_EMPTY
    lookup = index if index is not None else build_loxone_setpoint_io_index()
    field = lookup.get(name, "")
    if field and is_live_write_field(field):
        return field
    # Direct EHAL key stored as io (rare)
    if is_live_write_field(name):
        return name
    return _MAPPING_EMPTY


def ha_setpoint_mapping(entities: dict[str, str] | None) -> dict[str, str]:
    ents = entities if isinstance(entities, dict) else {}
    out: dict[str, str] = {}
    for field in SETPOINT_FIELDS:
        entity_id = str(ents.get(field) or "").strip()
        if entity_id:
            out[field] = entity_id
    return out


def parse_check_wert(detail: str, *, passed: bool) -> str:
    """Extract Wert from LoxoneCheck.detail when passed (``Wert=…`` / ``raw=…``)."""
    text = str(detail or "")
    if not passed:
        return ""
    for prefix in ("Wert=", "raw=", "Start="):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def ordered_union(primary: Sequence[str], extras: Sequence[str]) -> list[str]:
    """Keep primary order, then append extras not already present."""
    seen: set[str] = set()
    out: list[str] = []
    for name in list(primary) + list(extras):
        key = str(name or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out
