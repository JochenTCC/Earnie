"""EHAL Live-Lesen / Live-Schreiben table helpers (field ↔ backend Mapping).

Field tables live in ``integrations.ehal_debug_fields`` and the HA/OpenEMS mapping
helpers in ``integrations.ehal_debug_ha``; all names stay importable from here.
"""
from __future__ import annotations

from typing import Sequence

from integrations.ehal_debug_fields import (  # noqa: F401 — re-exports (field tables)
    _MAPPING_DERIVED,
    _MAPPING_EMPTY,
    BATTERY_ESS_LIVE_READ_KINDS,
    BATTERY_ESS_LIVE_WRITE_KINDS,
    BATTERY_SOURCE_SELECT_KIND,
    CONSUMER_ENERGY_LIVE_READ_FIELDS,
    EV_LIVE_READ_FIELDS,
    EV_LIVE_WRITE_FIELDS,
    FILTER_LIVE_READ_FIELDS,
    INVERTER_LIVE_READ_KINDS,
    INVERTER_LIVE_WRITE_KINDS,
    NETWORK_LIVE_READ_FIELDS,
    NETWORK_LIVE_WRITE_FIELDS,
    PLANT_ESS_LIVE_READ_KINDS,
    PLANT_HOUSE_LIVE_READ_FIELDS,
    PLANT_LIVE_READ_FIELDS,
    PLANT_LIVE_WRITE_FIELDS,
    PV_LIVE_READ_KINDS,
    THERMAL_ANNUAL_LIVE_READ_FIELDS,
    THERMAL_LIVE_READ_FIELDS,
)
from integrations.ehal_debug_ha import (  # noqa: F401 — re-exports (HA / OpenEMS mapping)
    _binding_map,
    _consumers_from_house_doc,
    _ha_live_consumers,
    expand_ha_telemetry_for_live,
    expand_ha_writes_for_live,
    ha_entity_scoped_live_mapping,
    ha_setpoint_mapping,
    ha_telemetry_mapping,
    openems_setpoint_mapping,
    openems_telemetry_mapping,
)



def is_live_read_field(field: str) -> bool:
    """True for Live-Lesen rows (``sens_*`` / ``get_*`` / flex / qualified IDs)."""
    from ehal.ess_fields import ess_field_kind
    from ehal.flex_fields import is_flex_live_read_field
    from ehal.inverter_fields import inv_field_kind
    from ehal.push_signals import REQUEST_OPTIMIZE_ID
    from ehal.qualified_ids import field_kind

    name = str(field or "").strip()
    if ":" in name:
        name = name.split(":", 1)[1]
    if name == REQUEST_OPTIMIZE_ID:
        return True
    kind = ess_field_kind(name) or inv_field_kind(name) or field_kind(name)
    return (
        kind.startswith("sens_")
        or kind.startswith("get_")
        or is_flex_live_read_field(name)
    )


def is_live_write_field(field: str) -> bool:
    """True for Live-Schreiben rows (``set_*`` / flex ``set_enable``)."""
    from ehal.ess_fields import ess_field_kind
    from ehal.flex_fields import KIND_SET_ENABLE, flex_field_kind
    from ehal.inverter_fields import inv_field_kind
    from ehal.qualified_ids import field_kind

    name = str(field or "").strip()
    if ":" in name:
        name = name.split(":", 1)[1]
    kind = ess_field_kind(name) or inv_field_kind(name) or field_kind(name)
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


def _all_live_inverters() -> list[dict]:
    """Inverters from ``components.json`` (optional EHAL role)."""
    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return []
        doc = load_components_document(path)
        raw = doc.get("inverters") if isinstance(doc, dict) else []
        if not isinstance(raw, list):
            return []
        return [
            inv
            for inv in raw
            if isinstance(inv, dict) and str(inv.get("id") or "").strip()
        ]
    except Exception:
        return []


def _all_live_pv_systems() -> list[dict]:
    """PV systems from ``components.json`` (optional entity-scoped pv.*)."""
    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return []
        doc = load_components_document(path)
        raw = doc.get("pv_systems") if isinstance(doc, dict) else []
        if not isinstance(raw, list):
            return []
        return [
            pv
            for pv in raw
            if isinstance(pv, dict) and str(pv.get("id") or "").strip()
        ]
    except Exception:
        return []


def expected_live_read_fields(*, network_backend: bool = False) -> list[str]:
    """Canonical Live-Lesen field ids (plant + batteries + inverters + PV + consumers)."""
    if network_backend:
        return list(NETWORK_LIVE_READ_FIELDS)
    fields = _plant_entity_live_read_fields(_all_live_batteries())
    for consumer in _all_live_consumers():
        fields.extend(_consumer_live_read_fields(consumer))
    from ehal.push_signals import REQUEST_OPTIMIZE_ID

    fields.append(REQUEST_OPTIMIZE_ID)
    return fields


def _plant_entity_live_read_fields(batteries: list[dict]) -> list[str]:
    """Plant, battery, inverter and PV-system Live-Lesen ids."""
    from ehal.ess_fields import ess_field
    from ehal.inverter_fields import inv_field
    from ehal.pv_fields import pv_field
    from ehal.qualified_ids import qualified_plant_id

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
    for inverter in _all_live_inverters():
        iid = str(inverter.get("id") or "").strip()
        if not iid:
            continue
        fields.extend(inv_field(iid, kind) for kind in INVERTER_LIVE_READ_KINDS)
    for pv in _all_live_pv_systems():
        pid = str(pv.get("id") or "").strip()
        if not pid:
            continue
        fields.extend(pv_field(pid, kind) for kind in PV_LIVE_READ_KINDS)
    return fields


def _consumer_live_read_fields(consumer: dict) -> list[str]:
    """Live-Lesen ids of one flexible consumer (EV / filter / generic / thermal)."""
    cid = str(consumer.get("id") or "").strip()
    if not cid:
        return []
    fields: list[str] = []
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
    """Canonical Live-Schreiben ids (plant + batteries + inverters + EV + flex)."""
    from ehal.ess_fields import ess_field
    from ehal.flex_fields import flex_set_enable
    from ehal.inverter_fields import inv_field
    from ehal.qualified_ids import qualified_plant_id
    from settings.ehal_marker_resolve import marker_flex_enable

    batteries = _all_live_batteries()
    if network_backend:
        fields = [
            f for f in NETWORK_LIVE_WRITE_FIELDS if f != BATTERY_SOURCE_SELECT_KIND
        ]
        _append_standby_source_select_fields(fields, batteries)
        for inverter in _all_live_inverters():
            iid = str(inverter.get("id") or "").strip()
            if iid:
                fields.extend(
                    inv_field(iid, kind) for kind in INVERTER_LIVE_WRITE_KINDS
                )
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
    for inverter in _all_live_inverters():
        iid = str(inverter.get("id") or "").strip()
        if not iid:
            continue
        fields.extend(inv_field(iid, kind) for kind in INVERTER_LIVE_WRITE_KINDS)
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
    """Entity-scoped ``ess.{slug}.set_*`` Merkers from components batteries."""
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
    from ehal.flex_fields import flex_set_enable
    from settings.ehal_marker_resolve import (
        marker_flex_enable,
        marker_set_evcs_max_current,
        marker_set_evcs_mode,
    )

    index: dict[str, str] = {}
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
        return field
    # Direct EHAL key / Q8 activation id stored as io
    if is_live_write_field(name):
        canon = canonicalize_live_display_field(name)
        if canon:
            return canon
        return name
    return _MAPPING_EMPTY
















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
