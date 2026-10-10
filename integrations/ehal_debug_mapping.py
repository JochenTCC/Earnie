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

# House-wide plant reads (grid kinds are storage-bare; Live shows grid.meter.*).
PLANT_HOUSE_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_grid_power_active",
    "sens_pv_production_active",
    "sens_power_consumers",
    "sens_temperature_outside",
    "sens_absent_mode",
    "get_grid_export_power_limit",
    "sens_pv_energy",
    "sens_grid_energy_import",
    "sens_grid_energy_export",
)

# Bare plant ESS kinds — Live rows only when no ehal-mappable battery exists.
PLANT_ESS_LIVE_READ_KINDS: tuple[str, ...] = (
    "sens_ess_soc",
    "sens_ess_power",
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)

# Union for callers that still inspect the full plant read set.
PLANT_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_grid_power_active",
    "sens_pv_production_active",
    "sens_ess_soc",
    "sens_ess_power",
    "sens_power_consumers",
    "sens_temperature_outside",
    "sens_absent_mode",
    "get_grid_export_power_limit",
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
    "sens_pv_energy",
    "sens_grid_energy_import",
    "sens_grid_energy_export",
)

CONSUMER_ENERGY_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_energy_total",
)

# Per-battery Pattern B read kinds (2.7.m).
BATTERY_ESS_LIVE_READ_KINDS: tuple[str, ...] = (
    "sens_ess_soc",
    "sens_ess_power",
    "sens_ess_energy_charge",
    "sens_ess_energy_discharge",
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)

BATTERY_ESS_LIVE_WRITE_KINDS: tuple[str, ...] = (
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_mode",
)

BATTERY_SOURCE_SELECT_KIND = "set_ess_source_select"

PLANT_LIVE_WRITE_FIELDS: tuple[str, ...] = (
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_mode",
    "set_grid_export_power_limit",
)
EV_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_evcs_active_power",
    "sens_evcs_connected",
    "sens_evcs_soc_act",
    "get_evcs_nominal_current",
    "sens_evcs_bat_capacity",
    "get_evcs_ready_by_time",
    "get_evcs_limit_soc",
    "get_evcs_soc_min_immediate",
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

THERMAL_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_temperature_water",
    "get_temperature_water_setpoint",
    "get_temperature_tolerance_c",
    "sens_heating_active",
)

THERMAL_ANNUAL_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_temperature_heat_storage",
    "sens_temperature_heat_storage_low",
)

NETWORK_LIVE_READ_FIELDS: tuple[str, ...] = TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL
NETWORK_LIVE_WRITE_FIELDS: tuple[str, ...] = SETPOINT_FIELDS


def is_live_read_field(field: str) -> bool:
    """True for Live-Lesen rows (``sens_*`` / ``get_*`` / flex / qualified IDs)."""
    from ehal.ess_fields import ess_field_kind
    from ehal.flex_fields import is_flex_live_read_field
    from ehal.qualified_ids import field_kind

    name = str(field or "").strip()
    if ":" in name:
        name = name.split(":", 1)[1]
    kind = ess_field_kind(name) or field_kind(name)
    return (
        kind.startswith("sens_")
        or kind.startswith("get_")
        or is_flex_live_read_field(name)
    )


def is_live_write_field(field: str) -> bool:
    """True for Live-Schreiben rows (``set_*`` / flex ``set_enable``)."""
    from ehal.ess_fields import ess_field_kind
    from ehal.flex_fields import KIND_SET_ENABLE, flex_field_kind
    from ehal.qualified_ids import field_kind

    name = str(field or "").strip()
    if ":" in name:
        name = name.split(":", 1)[1]
    kind = ess_field_kind(name) or field_kind(name)
    if kind.startswith("set_"):
        return True
    if kind == KIND_SET_ENABLE:
        return True
    return flex_field_kind(name) == KIND_SET_ENABLE


def _consumer_is_ev(consumer: dict) -> bool:
    if str(consumer.get("type") or "") == "ev":
        return True
    sched = consumer.get("charging_schedule") or {}
    if isinstance(sched, dict):
        if sched.get("enabled"):
            return True
        lox = sched.get("loxone") if isinstance(sched.get("loxone"), dict) else {}
        for key in (
            "plugged_in_name",
            "actual_soc_name",
            "ready_by_time_name",
            "battery_capacity_kwh_name",
            "nominal_power_kw_name",
            "sens_evcs_connected",
            "sens_evcs_soc_act",
            "get_evcs_ready_by_time",
        ):
            if str(lox.get(key) or "").strip():
                return True
    bindings = consumer.get("ehal_bindings")
    if isinstance(bindings, dict):
        for key, value in bindings.items():
            name = str(key or "")
            if name.startswith(("sens_evcs_", "get_evcs_", "set_evcs_")) and str(
                value or ""
            ).strip():
                return True
    return False


def _consumer_type_for_qualified_id(consumer: dict) -> str:
    """Consumer type for qualified Live-Lesen IDs (infer when bridge dropped type)."""
    ctype = str(consumer.get("type") or "").strip()
    if ctype:
        return ctype
    if _consumer_is_ev(consumer):
        return "ev"
    if _consumer_is_thermal_annual(consumer):
        return "thermal_annual"
    if _consumer_is_thermal(consumer):
        return "thermal_rc"
    return ""


def live_read_consumer_field(consumer: dict, field_key: str) -> str:
    """Qualified Live-Lesen EHAL ID (same form as Push-Inbox)."""
    from ehal.qualified_ids import qualified_consumer_id

    cid = str(consumer.get("id") or "").strip()
    return qualified_consumer_id(cid, _consumer_type_for_qualified_id(consumer), field_key)


def live_write_consumer_field(consumer: dict, field_key: str) -> str:
    """Qualified Live-Schreiben EHAL ID (same form as status.json / VI)."""
    return live_read_consumer_field(consumer, field_key)


def has_mappable_live_batteries() -> bool:
    """True when components.json has at least one EHAL-mappable battery."""
    return bool(_all_live_batteries())


def canonicalize_live_display_field(
    field: str,
    *,
    has_batteries: bool | None = None,
) -> str | None:
    """Exchange ID for Live tables, or None to drop an obsolete bare ESS alias."""
    from ehal.ess_fields import is_plant_flat_ess_field
    from ehal.qualified_ids import GRID_KINDS, field_kind, qualified_plant_id

    name = str(field or "").strip()
    if not name:
        return None
    if ":" in name:
        cid, rest = name.split(":", 1)
        cid = cid.strip()
        rest = rest.strip()
        if cid and rest:
            for consumer in _all_live_consumers():
                if str(consumer.get("id") or "").strip() == cid:
                    return live_write_consumer_field(consumer, rest)
        return rest
    kind = field_kind(name)
    if kind in GRID_KINDS and ("." not in name or name == kind):
        return qualified_plant_id(kind)
    batteries = (
        has_mappable_live_batteries() if has_batteries is None else has_batteries
    )
    if batteries and is_plant_flat_ess_field(name):
        return None
    return name


def _consumer_is_filter(consumer: dict) -> bool:
    cid = str(consumer.get("id") or "").strip().lower()
    if cid == "pool_filter":
        return True
    if consumer.get("daily_target_source") == "loxone_remaining_hours":
        return True
    fsched = consumer.get("filter_schedule")
    return isinstance(fsched, dict) and bool(fsched.get("enabled"))


def _consumer_is_thermal(consumer: dict) -> bool:
    """True for Pool/SwimSpa thermal_rc (or bindings with water-temp markers)."""
    if str(consumer.get("type") or "") == "thermal_rc":
        return True
    bindings = consumer.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return False
    return any(
        str(bindings.get(field) or "").strip() for field in THERMAL_LIVE_READ_FIELDS
    )


def _consumer_is_thermal_annual(consumer: dict) -> bool:
    if str(consumer.get("type") or "") == "thermal_annual":
        return True
    bindings = consumer.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return False
    return any(
        str(bindings.get(field) or "").strip()
        for field in THERMAL_ANNUAL_LIVE_READ_FIELDS
    )


def _all_live_consumers() -> list[dict]:
    """House-profile + flex consumers (including unmapped)."""
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
    return list(by_id.values())


def _all_live_batteries() -> list[dict]:
    """EHAL-mappable batteries only (excludes virtual powerstations)."""
    try:
        from house_config.components_store import load_components_document
        from house_config.powerstation import ehal_mappable_batteries
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return []
        doc = load_components_document(path)
        raw = doc.get("batteries") if isinstance(doc, dict) else []
        return ehal_mappable_batteries(raw if isinstance(raw, list) else [])
    except Exception:
        return []


def expected_live_read_fields(*, network_backend: bool = False) -> list[str]:
    """Canonical Live-Lesen field ids (plant + batteries + consumers), including unmapped."""
    from ehal.ess_fields import ess_field
    from ehal.qualified_ids import qualified_plant_id

    if network_backend:
        return list(NETWORK_LIVE_READ_FIELDS)
    batteries = _all_live_batteries()
    has_batteries = bool(batteries)
    # Plant GRID_KINDS exchange as ``grid.meter.*`` (same form as Push-Inbox).
    plant_names = list(PLANT_HOUSE_LIVE_READ_FIELDS)
    if not has_batteries:
        plant_names.extend(PLANT_ESS_LIVE_READ_KINDS)
    fields = [qualified_plant_id(name) for name in plant_names]
    for battery in batteries:
        bid = str(battery.get("id") or "").strip()
        if not bid:
            continue
        fields.extend(ess_field(bid, kind) for kind in BATTERY_ESS_LIVE_READ_KINDS)
    for consumer in _all_live_consumers():
        cid = str(consumer.get("id") or "").strip()
        if not cid:
            continue
        if _consumer_is_ev(consumer):
            fields.extend(
                live_read_consumer_field(consumer, name) for name in EV_LIVE_READ_FIELDS
            )
            fields.extend(
                live_read_consumer_field(consumer, name)
                for name in CONSUMER_ENERGY_LIVE_READ_FIELDS
            )
        elif _consumer_is_filter(consumer):
            from ehal.flex_fields import flex_sens_power_act

            fields.append(live_read_consumer_field(consumer, flex_sens_power_act(cid)))
            fields.extend(
                live_read_consumer_field(consumer, name)
                for name in FILTER_LIVE_READ_FIELDS
            )
            fields.extend(
                live_read_consumer_field(consumer, name)
                for name in CONSUMER_ENERGY_LIVE_READ_FIELDS
            )
        else:
            from ehal.flex_fields import (
                flex_sens_consumer_active,
                flex_sens_power_act,
            )

            fields.append(live_read_consumer_field(consumer, flex_sens_power_act(cid)))
            fields.append(
                live_read_consumer_field(consumer, flex_sens_consumer_active(cid))
            )
            fields.extend(
                live_read_consumer_field(consumer, name)
                for name in CONSUMER_ENERGY_LIVE_READ_FIELDS
            )
            if _consumer_is_thermal(consumer):
                fields.extend(
                    live_read_consumer_field(consumer, name)
                    for name in THERMAL_LIVE_READ_FIELDS
                )
            if _consumer_is_thermal_annual(consumer):
                fields.extend(
                    live_read_consumer_field(consumer, name)
                    for name in THERMAL_ANNUAL_LIVE_READ_FIELDS
                )
    return fields


def _append_standby_source_select_fields(
    fields: list[str], batteries: list[dict]
) -> None:
    from ehal.ess_fields import ess_field
    from house_config.powerstation import (
        BACKING_PHYSICAL,
        ROLE_STANDBY_BACKUP,
        is_powerstation,
    )

    for battery in batteries:
        bid = str(battery.get("id") or "").strip()
        if not bid:
            continue
        if not is_powerstation(battery):
            continue
        if str(battery.get("role") or "") != ROLE_STANDBY_BACKUP:
            continue
        if str(battery.get("backing") or "") != BACKING_PHYSICAL:
            continue
        fields.append(ess_field(bid, BATTERY_SOURCE_SELECT_KIND))


def expected_live_write_fields(*, network_backend: bool = False) -> list[str]:
    """Canonical Live-Schreiben ids (plant + batteries + EV + flex Freigabe)."""
    from ehal.ess_fields import ess_field
    from ehal.flex_fields import flex_set_enable
    from ehal.qualified_ids import qualified_plant_id
    from settings.ehal_marker_resolve import marker_flex_enable

    batteries = _all_live_batteries()
    if network_backend:
        fields = [
            f for f in NETWORK_LIVE_WRITE_FIELDS if f != BATTERY_SOURCE_SELECT_KIND
        ]
        _append_standby_source_select_fields(fields, batteries)
        return fields
    has_batteries = bool(batteries)
    fields: list[str] = []
    if not has_batteries:
        fields.extend(BATTERY_ESS_LIVE_WRITE_KINDS)
    fields.append(qualified_plant_id("set_grid_export_power_limit"))
    for battery in batteries:
        bid = str(battery.get("id") or "").strip()
        if not bid:
            continue
        fields.extend(ess_field(bid, kind) for kind in BATTERY_ESS_LIVE_WRITE_KINDS)
    _append_standby_source_select_fields(fields, batteries)
    for consumer in _all_live_consumers():
        cid = str(consumer.get("id") or "").strip()
        if not cid:
            continue
        if _consumer_is_ev(consumer):
            fields.extend(
                live_write_consumer_field(consumer, name) for name in EV_LIVE_WRITE_FIELDS
            )
            continue
        if marker_flex_enable(consumer):
            fields.append(live_write_consumer_field(consumer, flex_set_enable(cid)))
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


def _append_plant_binding_io(
    index: dict[str, str],
    *,
    field: str,
    house: dict | None,
) -> None:
    from house_config.ehal_bindings import resolve_plant_binding
    from ehal.qualified_ids import qualified_plant_id

    if house is None:
        return
    io_name = str(resolve_plant_binding(house, field) or "").strip()
    if io_name and io_name not in index:
        index[io_name] = qualified_plant_id(field)


def _append_battery_write_io(index: dict[str, str]) -> None:
    """Pattern B ``ess.{slug}.set_*`` Merkers from components batteries."""
    from ehal.ess_fields import binding_address, ess_field
    from house_config.powerstation import (
        BACKING_PHYSICAL,
        ROLE_STANDBY_BACKUP,
        is_powerstation,
    )

    for battery in _all_live_batteries():
        bid = str(battery.get("id") or "").strip()
        if not bid:
            continue
        bindings = battery.get("ehal_bindings")
        if not isinstance(bindings, dict):
            continue
        kinds = list(BATTERY_ESS_LIVE_WRITE_KINDS)
        if (
            is_powerstation(battery)
            and str(battery.get("role") or "") == ROLE_STANDBY_BACKUP
            and str(battery.get("backing") or "") == BACKING_PHYSICAL
        ):
            kinds.append(BATTERY_SOURCE_SELECT_KIND)
        for kind in kinds:
            field = ess_field(bid, kind)
            io_name = binding_address(bindings, bid, kind)
            if not io_name:
                io_name = str(bindings.get(kind) or "").strip()
            # Q8: empty Merker is an activation flag — index the qualified id.
            if not io_name and (field in bindings or kind in bindings):
                io_name = field
            if io_name and io_name not in index:
                index[io_name] = field


def build_loxone_setpoint_io_index(*, include_write_aliases: bool = True) -> dict[str, str]:
    """Merker IO-Name → EHAL write field (plant + batteries + EV + flex)."""
    import config
    from ehal.flex_fields import flex_set_enable
    from settings.ehal_marker_resolve import (
        marker_flex_enable,
        marker_set_evcs_max_current,
        marker_set_evcs_mode,
    )

    index: dict[str, str] = {}
    has_batteries = has_mappable_live_batteries()
    if not has_batteries:
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

    house: dict | None = None
    try:
        from optimizer.live_export_limit import load_house_doc

        loaded = load_house_doc()
        house = loaded if isinstance(loaded, dict) else None
    except Exception:  # noqa: BLE001 — status JSON still works without plant doc
        house = None
    _append_plant_binding_io(
        index, field="set_grid_export_power_limit", house=house
    )
    _append_battery_write_io(index)
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
                    index[io_name] = live_write_consumer_field(consumer, field)
            continue
        enable = str(marker_flex_enable(consumer) or "").strip()
        if enable:
            index[enable] = live_write_consumer_field(consumer, flex_set_enable(cid))

    if not include_write_aliases:
        return index

    return index


def loxone_write_field_to_io() -> dict[str, str]:
    """EHAL write field → configured Merker (primary bindings only, no aliases)."""
    return {
        field: io
        for io, field in build_loxone_setpoint_io_index(include_write_aliases=False).items()
    }


def _plant_flat_ess_to_primary_exchange(name: str) -> str:
    """Bare plant ESS ``set_*`` → ``ess.<primary>.set_*`` when batteries exist."""
    from ehal.ess_fields import ess_field, is_plant_flat_ess_field

    kind = str(name or "").strip()
    if not kind or not is_plant_flat_ess_field(kind):
        return ""
    if not has_mappable_live_batteries():
        return kind
    try:
        from integrations.loxone_adapter import primary_ess_id_for_plant_read
    except Exception:  # noqa: BLE001
        return ""
    bid = primary_ess_id_for_plant_read()
    return ess_field(bid, kind) if bid else ""


def resolve_loxone_write_field(io_name: str, index: dict[str, str] | None = None) -> str:
    """Reverse-map Merker → EHAL write field (or empty if unknown / not a write)."""
    name = str(io_name or "").strip()
    if not name:
        return _MAPPING_EMPTY
    lookup = index if index is not None else build_loxone_setpoint_io_index()
    field = lookup.get(name, "")
    if field and is_live_write_field(field):
        canon = canonicalize_live_display_field(field)
        if canon:
            return canon
        upgraded = _plant_flat_ess_to_primary_exchange(field)
        if upgraded:
            return upgraded
        return field
    # Direct EHAL key / Q8 activation id stored as io
    if is_live_write_field(name):
        canon = canonicalize_live_display_field(name)
        if canon:
            return canon
        upgraded = _plant_flat_ess_to_primary_exchange(name)
        if upgraded:
            return upgraded
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
        live = _all_live_consumers()
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


def ha_pattern_b_live_mapping(house_doc: dict | None = None) -> dict[str, str]:
    """Entity-centric EHAL-Feld → HA entity_id (exchange IDs for Live tables)."""
    if house_doc is None:
        from ui.house_config_io import load_house_profiles

        house_doc = load_house_profiles()
    from ehal.qualified_ids import qualified_plant_id

    out: dict[str, str] = {}
    plant = house_doc.get("plant") if isinstance(house_doc.get("plant"), dict) else {}
    for field, entity_id in _binding_map(plant.get("ehal_bindings")).items():
        if is_live_read_field(field):
            out[qualified_plant_id(field)] = entity_id
        else:
            out[qualified_plant_id(field)] = entity_id
    for consumer in _ha_live_consumers(house_doc):
        if not str(consumer.get("id") or "").strip():
            continue
        for field, entity_id in _binding_map(consumer.get("ehal_bindings")).items():
            if is_live_read_field(field):
                out[live_read_consumer_field(consumer, field)] = entity_id
            else:
                out[live_write_consumer_field(consumer, field)] = entity_id
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
        if not cid or not _consumer_is_ev(consumer):
            continue
        for name in EV_LIVE_READ_FIELDS:
            if name in flat:
                out[live_read_consumer_field(consumer, name)] = flat[name]
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
        if str(consumer.get("id") or "").strip() and _consumer_is_ev(consumer):
            ev_consumer = consumer
            break
    out: list[dict[str, Any]] = []
    for entry in writes:
        row = dict(entry)
        field = str(row.get("field") or "").strip()
        if ev_consumer is not None and field in EV_LIVE_WRITE_FIELDS:
            row["field"] = live_write_consumer_field(ev_consumer, field)
        else:
            canon = canonicalize_live_display_field(field)
            if canon:
                row["field"] = canon
        out.append(row)
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


def _canonicalize_live_union_field(field: str) -> str:
    """Qualify bare grid / expand ``{cid}:field``; keep bare ESS (expected lists omit them)."""
    from ehal.qualified_ids import GRID_KINDS, field_kind, qualified_plant_id

    name = str(field or "").strip()
    if not name:
        return ""
    if ":" in name:
        cid, rest = name.split(":", 1)
        cid = cid.strip()
        rest = rest.strip()
        if cid and rest:
            for consumer in _all_live_consumers():
                if str(consumer.get("id") or "").strip() == cid:
                    return live_write_consumer_field(consumer, rest)
        return rest
    kind = field_kind(name)
    if kind in GRID_KINDS and ("." not in name or name == kind):
        return qualified_plant_id(kind)
    return name


def ordered_union(primary: Sequence[str], extras: Sequence[str]) -> list[str]:
    """Keep primary order, then append extras; qualify bare grid / colon aliases."""
    seen: set[str] = set()
    out: list[str] = []
    for name in list(primary) + list(extras):
        key = _canonicalize_live_union_field(str(name or "").strip())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out
