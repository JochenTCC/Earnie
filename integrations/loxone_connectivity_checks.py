"""Per-entity Loxone live-read checks (split from loxone_connectivity)."""
from __future__ import annotations

from integrations.loxone_connectivity_base import (
    _append_io_check,
)


def ev_ehal_binding_collisions(consumer: dict) -> list[tuple[str, str, list[str]]]:
    """Return (io_name, detail, fields) when distinct EV EHAL roles share one Merker."""
    from collections import defaultdict

    from settings.ehal_marker_resolve import (
        marker_get_evcs_nominal_current,
        marker_get_evcs_soc_min_immediate,
        marker_sens_evcs_active_power,
        marker_sens_evcs_connected,
        marker_set_evcs_max_current,
        marker_set_evcs_mode,
    )

    roles = {
        "sens_evcs_active_power": marker_sens_evcs_active_power(consumer),
        "sens_evcs_connected": marker_sens_evcs_connected(consumer),
        "set_evcs_max_current": marker_set_evcs_max_current(consumer),
        "set_evcs_mode": marker_set_evcs_mode(consumer),
        "get_evcs_nominal_current": marker_get_evcs_nominal_current(consumer),
        "get_evcs_soc_min_immediate": marker_get_evcs_soc_min_immediate(consumer),
    }
    by_io: dict[str, list[str]] = defaultdict(list)
    for field, io_name in roles.items():
        name = str(io_name or "").strip()
        if name:
            by_io[name].append(field)
    out: list[tuple[str, str, list[str]]] = []
    for io_name, fields in sorted(by_io.items()):
        if len(fields) < 2:
            continue
        detail = (
            f"EV ehal_bindings collision on '{io_name}': "
            + ", ".join(fields)
            + " (writes/reads must use distinct Merker)"
        )
        out.append((io_name, detail, fields))
    return out


def _append_ev_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from integrations.ehal_debug_mapping import live_read_consumer_field
    from settings.ehal_marker_resolve import (
        marker_get_evcs_limit_soc,
        marker_get_evcs_ready_by_time,
        marker_get_evcs_soc_min_immediate,
        marker_sens_evcs_active_power,
        marker_sens_evcs_bat_capacity,
        marker_sens_evcs_connected,
        marker_get_evcs_nominal_current,
        marker_sens_evcs_soc_act,
    )

    # Force EV namespace when type was dropped by the planning bridge.
    ev = dict(consumer)
    if not str(ev.get("type") or "").strip():
        ev["type"] = "ev"
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "sens_evcs_active_power"),
        marker_sens_evcs_active_power(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "sens_evcs_connected"),
        marker_sens_evcs_connected(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "sens_evcs_soc_act"),
        marker_sens_evcs_soc_act(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "sens_evcs_bat_capacity"),
        marker_sens_evcs_bat_capacity(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "get_evcs_nominal_current"),
        marker_get_evcs_nominal_current(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "get_evcs_ready_by_time"),
        marker_get_evcs_ready_by_time(consumer),
        {"read_raw": True, "warn_if_missing": True},
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "get_evcs_limit_soc"),
        marker_get_evcs_limit_soc(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "get_evcs_soc_min_immediate"),
        marker_get_evcs_soc_min_immediate(consumer),
    )


def _append_flex_power_check(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from ehal.flex_fields import flex_sens_consumer_active, flex_sens_power_act
    from integrations.ehal_debug_mapping import live_read_consumer_field
    from settings.ehal_marker_resolve import (
        marker_flex_power,
        marker_sens_consumer_active,
    )

    cid = consumer["id"]
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, flex_sens_power_act(cid)),
        marker_flex_power(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, flex_sens_consumer_active(cid)),
        marker_sens_consumer_active(consumer),
    )


def _append_filter_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from integrations.ehal_debug_mapping import live_read_consumer_field
    from settings.ehal_marker_resolve import (
        marker_get_filter_native_duration_hours,
        marker_get_filter_native_start_hour,
        marker_get_filter_remaining_hours,
        marker_sens_filter_active,
    )

    _append_flex_power_check(checks, consumer)
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_filter_remaining_hours"),
        marker_get_filter_remaining_hours(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_filter_active"),
        marker_sens_filter_active(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_filter_native_start_hour"),
        marker_get_filter_native_start_hour(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_filter_native_duration_hours"),
        marker_get_filter_native_duration_hours(consumer),
    )


def _append_thermal_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from integrations.ehal_debug_mapping import live_read_consumer_field
    from settings.ehal_marker_resolve import (
        marker_get_temperature_tolerance_c,
        marker_get_temperature_water_setpoint,
        marker_sens_heating_active,
        marker_sens_temperature_water,
    )

    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_temperature_water"),
        marker_sens_temperature_water(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_temperature_water_setpoint"),
        marker_get_temperature_water_setpoint(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_temperature_tolerance_c"),
        marker_get_temperature_tolerance_c(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_heating_active"),
        marker_sens_heating_active(consumer),
    )


def _append_thermal_annual_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from integrations.ehal_debug_mapping import live_read_consumer_field
    from settings.ehal_marker_resolve import (
        marker_sens_temperature_heat_storage,
        marker_sens_temperature_heat_storage_low,
    )

    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_temperature_heat_storage"),
        marker_sens_temperature_heat_storage(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_temperature_heat_storage_low"),
        marker_sens_temperature_heat_storage_low(consumer),
    )


def _append_plant_energy_read_checks(
    checks: list[tuple[str, str, dict]],
    house_doc: dict | None,
) -> None:
    """Activated plant energy counters (push-only; Merker may be empty)."""
    from ehal.loxone_push_source import is_pushable_kind
    from ehal.qualified_ids import qualified_plant_id
    from integrations.loxone_meter_energy import (
        PLANT_ENERGY_FIELDS,
        energy_binding_activated,
    )

    if not isinstance(house_doc, dict):
        return
    plant = house_doc.get("plant") if isinstance(house_doc.get("plant"), dict) else {}
    bindings = plant.get("ehal_bindings") if isinstance(plant.get("ehal_bindings"), dict) else {}
    for field in PLANT_ENERGY_FIELDS:
        if not energy_binding_activated(bindings, field):
            continue
        label = qualified_plant_id(field)
        io_name = str(bindings.get(field) or "").strip()
        if not io_name and is_pushable_kind(field):
            io_name = label
        _append_io_check(checks, label, io_name)


def _append_pv_system_read_checks(checks: list[tuple[str, str, dict]]) -> None:
    """Per-PV-system entity-scoped reads from ``components.json``."""
    from ehal.loxone_push_source import is_pushable_kind
    from ehal.pv_fields import binding_address, pv_field
    from integrations.ehal_debug_mapping import PV_LIVE_READ_KINDS

    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return
        doc = load_components_document(path)
    except Exception:
        return
    raw = doc.get("pv_systems") if isinstance(doc, dict) else []
    if not isinstance(raw, list):
        return
    for pv in raw:
        if not isinstance(pv, dict):
            continue
        pid = str(pv.get("id") or "").strip()
        if not pid:
            continue
        bindings = pv.get("ehal_bindings")
        bind_map = bindings if isinstance(bindings, dict) else None
        for kind in PV_LIVE_READ_KINDS:
            field = pv_field(pid, kind)
            io_name = binding_address(bind_map, pid, kind)
            if not io_name and bind_map is not None and field in bind_map:
                if is_pushable_kind(kind):
                    io_name = field
            _append_io_check(checks, field, io_name)


def _append_inverter_read_checks(checks: list[tuple[str, str, dict]]) -> None:
    """Per-inverter entity-scoped reads from ``components.json`` (2.7.l P4)."""
    from ehal.inverter_fields import binding_address, inv_field
    from ehal.loxone_push_source import is_pushable_kind
    from integrations.ehal_debug_mapping import INVERTER_LIVE_READ_KINDS

    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return
        doc = load_components_document(path)
    except Exception:
        return
    raw = doc.get("inverters") if isinstance(doc, dict) else []
    if not isinstance(raw, list):
        return
    for inverter in raw:
        if not isinstance(inverter, dict):
            continue
        iid = str(inverter.get("id") or "").strip()
        if not iid:
            continue
        bindings = inverter.get("ehal_bindings")
        bind_map = bindings if isinstance(bindings, dict) else None
        for kind in INVERTER_LIVE_READ_KINDS:
            field = inv_field(iid, kind)
            io_name = binding_address(bind_map, iid, kind)
            if not io_name and bind_map is not None and field in bind_map:
                if is_pushable_kind(kind):
                    io_name = field
            _append_io_check(checks, field, io_name)


def _append_battery_ess_read_checks(checks: list[tuple[str, str, dict]]) -> None:
    """Per-battery entity-scoped ESS reads from ``components.json`` (2.7.m)."""
    from ehal.ess_fields import binding_address, ess_field
    from ehal.loxone_push_source import is_pushable_kind
    from integrations.ehal_debug_mapping import BATTERY_ESS_LIVE_READ_KINDS

    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return
        doc = load_components_document(path)
    except Exception:
        return
    from house_config.powerstation import ehal_mappable_batteries

    batteries = doc.get("batteries") if isinstance(doc, dict) else []
    for battery in ehal_mappable_batteries(
        batteries if isinstance(batteries, list) else []
    ):
        bid = str(battery.get("id") or "").strip()
        if not bid:
            continue
        bindings = battery.get("ehal_bindings")
        bind_map = bindings if isinstance(bindings, dict) else None
        for kind in BATTERY_ESS_LIVE_READ_KINDS:
            field = ess_field(bid, kind)
            io_name = binding_address(bind_map, bid, kind)
            if not io_name and bind_map is not None and field in bind_map:
                if is_pushable_kind(kind):
                    io_name = field
            _append_io_check(checks, field, io_name)
