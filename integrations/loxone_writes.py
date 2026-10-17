"""Loxone write helpers: setpoints, ESS, flexible consumer outputs."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import config
from integrations.loxone_comm_trace import LoxoneWriteRecord
from settings.ehal_marker_resolve import (
    marker_flex_enable,
    marker_set_evcs_max_current,
    marker_set_evcs_mode,
)
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere
from settings.flexible_consumers import runtime_consumer_id

logger = logging.getLogger(__name__)


def resolve_consumer_nominal_power_kw(consumer: dict) -> float:
    from integrations.loxone_live_power import resolve_consumer_nominal_power_kw as _impl

    return _impl(consumer)


def _publish_setpoint_traced(
    qualified_id: str,
    value: float,
    *,
    io_name: str = "",
) -> LoxoneWriteRecord:
    """Publish a setpoint into the status.json ledger (2.7.q Q5; no Merker HTTP)."""
    from integrations.ehal_write import write_field
    from runtime_store.shadow.writes import block_write_if_shadow

    written_at = datetime.now().isoformat(timespec="seconds")
    qid = str(qualified_id or "").strip()
    display = str(io_name or qid or "").strip()
    if not qid:
        return LoxoneWriteRecord(
            io_name=display, value=float(value), success=False, written_at=written_at
        )

    if block_write_if_shadow(
        backend="loxone",
        target=display or qid,
        value=float(value),
        source="loxone_writes",
    ):
        return LoxoneWriteRecord(
            io_name=display, value=float(value), success=False, written_at=written_at
        )

    pub = write_field(qid, float(value))
    if pub.published:
        print(f"   ↳ EHAL publish: {qid} = {value}")
    return LoxoneWriteRecord(
        io_name=display,
        value=float(value),
        success=bool(pub.published),
        written_at=written_at,
    )


def map_ess_setpoints(
    mode: int,
    target_power_kw: float,
    max_charge_power_kw: float,
    max_discharge_power_kw: float | None = None,
) -> tuple[float | None, float, float, int]:
    """Design C1: (active_power_kw|None, charge_limit_kw, discharge_limit_kw, mode_hint).

    ``active_power_kw`` uses EHAL sign (+discharge, −charge). ``None`` means Automatik /
    Entladesperre without a forced Equals setpoint. Limits are true caps (kW magnitudes).
    ``mode_hint`` is for Loxone/HA (Huawei Steuerbefehl); OpenEMS ignores it.
    Battery-only: export caps travel on ``set_grid_export_power_limit`` (2.7.a).

    ``max_discharge_power_kw`` defaults to ``max_charge_power_kw`` for legacy single-max
    callers (pre-2.7.j).
    """
    max_charge = max(0.0, abs(float(max_charge_power_kw)))
    if max_discharge_power_kw is None:
        max_discharge = max_charge
    else:
        max_discharge = max(0.0, abs(float(max_discharge_power_kw)))
    target = max(0.0, abs(float(target_power_kw)))
    if mode == 1:  # MODE_ZWANGS_LADEN
        return -target, max_charge, 0.0, 1
    if mode == 2:  # MODE_ENTLADESPERRE
        return None, max_charge, 0.0, 1
    if mode == 3:  # MODE_ZWANGS_ENTLADEN
        return target, 0.0, max_discharge, 2
    return None, max_charge, max_discharge, 0


def flex_consumer_enable_value(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
) -> int | None:
    """Freigabe 0/1 für einen flexiblen Verbraucher (None wenn kein enable Merker)."""
    if not marker_flex_enable(consumer):
        return None

    cid = consumer["id"]
    power_kw = _effective_consumer_power_kw(consumer, consumer_powers, charging_contexts, cid)
    return 1 if power_kw > 1e-3 else 0


def _effective_consumer_power_kw(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    cid: str,
) -> float:
    power_kw = max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0))
    ctx = charging_contexts.get(cid)
    if ctx is not None and not ctx.get("active", True):
        return 0.0
    if ctx is not None and ctx.get("anticipated") and not ctx.get("plugged_in"):
        return 0.0
    return power_kw


def flex_consumer_power_setpoint_kw(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> float | None:
    """kW-Sollwert aus MILP (None wenn kein set_evcs_max_current / power_setpoint)."""
    from optimizer.consumer_power import loxone_control_outputs

    if not marker_set_evcs_max_current(consumer):
        return None

    cid = consumer["id"]
    planned_kw = _effective_consumer_power_kw(consumer, consumer_powers, charging_contexts, cid)
    pv_follow = int((consumer_pv_follow or {}).get(cid, 0) or 0)
    setpoint_kw, _ = loxone_control_outputs(consumer, planned_kw, pv_follow)
    return setpoint_kw


def flex_consumer_setpoint_amps(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> float | None:
    """set_evcs_max_current (A) from planned kW; None wenn kein Current-Merker."""
    setpoint_kw = flex_consumer_power_setpoint_kw(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    if setpoint_kw is None:
        return None
    voltage_v, phases = ev_nominal_power_conversion(consumer)
    return round(kw_to_ampere(setpoint_kw, voltage_v=voltage_v, phases=phases), 3)


def _skip_flexible_consumer_output(
    consumer: dict,
    charging_contexts: dict[str, dict],
) -> bool:
    ctx = charging_contexts.get(consumer["id"]) or {}
    return bool(ctx.get("skip_loxone_output"))


_EVCS_MODE_VALUES: dict[str, float] = {"off": 0.0, "pv": 1.0, "now": 2.0}


def _append_evcs_mode_writes(
    values: dict[str, float],
    consumer: dict,
    *,
    mode: str | None,
) -> None:
    """Write the canonical ``set_evcs_mode`` Merker (off=0, pv=1, now=2)."""
    mode_name = marker_set_evcs_mode(consumer)
    if not mode_name:
        return
    values[mode_name] = _EVCS_MODE_VALUES.get(str(mode or "").strip().lower(), 0.0)


def _immediate_skip_output_values(consumer: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    _append_evcs_mode_writes(values, consumer, mode="now")
    if values:
        logger.info(
            "Flex consumer %s -> Sofort laden: set_evcs_mode=now "
            "(kein Lade-Sollstrom von Earnie).",
            consumer["name"],
        )
    else:
        logger.info(
            "Flex consumer %s -> keine Steuerung (Sofort laden aktiv, Loxone regelt).",
            consumer["name"],
        )
    return values


def _evcs_current_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None,
    current_name: str,
) -> dict[str, float]:
    from optimizer.consumer_power import loxone_control_outputs, set_evcs_mode_for_plan

    amps = flex_consumer_setpoint_amps(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    if amps is None:
        return {}
    values = {str(current_name): float(amps)}
    cid = consumer["id"]
    planned_kw = _effective_consumer_power_kw(
        consumer, consumer_powers, charging_contexts, cid
    )
    plan_pv = int((consumer_pv_follow or {}).get(cid, 0) or 0)
    _, pv_out = loxone_control_outputs(consumer, planned_kw, plan_pv)
    mode = set_evcs_mode_for_plan(
        pv_follow=int(pv_out),
        immediate=False,
        charging=float(amps) > 1e-6,
    )
    _append_evcs_mode_writes(values, consumer, mode=mode)
    setpoint_kw = flex_consumer_power_setpoint_kw(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    logger.info(
        "Flex consumer %s -> Soll=%.2f A (%.2f kW), mode=%s "
        "(geplant %.2f kW, Loxone: %s)",
        consumer["name"],
        amps,
        setpoint_kw or 0.0,
        mode,
        max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0)),
        current_name,
    )
    return values


def _enable_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    enable_name: str,
) -> dict[str, float]:
    enabled = flex_consumer_enable_value(consumer, consumer_powers, charging_contexts)
    if enabled is None:
        return {}
    power_kw = max(0.0, float(consumer_powers.get(consumer["id"], 0.0) or 0.0))
    logger.info(
        "Flex consumer %s -> Freigabe=%s (optimiert %.2f kW, Loxone: %s)",
        consumer["name"],
        enabled,
        power_kw,
        enable_name,
    )
    return {str(enable_name): float(enabled)}


def _flexible_consumer_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> dict[str, float]:
    """Berechnet Loxone-Merker → Wert für einen flexiblen Verbraucher (ohne HTTP)."""
    if _skip_flexible_consumer_output(consumer, charging_contexts):
        return _immediate_skip_output_values(consumer)

    current_name = marker_set_evcs_max_current(consumer)
    enable_name = marker_flex_enable(consumer)
    if current_name:
        return _evcs_current_output_values(
            consumer,
            consumer_powers,
            charging_contexts,
            consumer_pv_follow,
            current_name,
        )

    if not enable_name:
        return {}
    return _enable_output_values(
        consumer, consumer_powers, charging_contexts, enable_name
    )


def _publish_flexible_consumer_outputs(
    consumer: dict, values: dict[str, float]
) -> list[LoxoneWriteRecord]:
    """Publish qualified IDs for flex/EV outputs (2.7.q Q5 push-only)."""
    from ehal.qualified_ids import qualified_consumer_id
    from integrations.ehal_debug_mapping import _consumer_type_for_qualified_id

    records: list[LoxoneWriteRecord] = []
    cid = str(consumer.get("id") or "").strip()
    if not cid or not values:
        return records
    ctype = _consumer_type_for_qualified_id(consumer)
    current = marker_set_evcs_max_current(consumer)
    mode = marker_set_evcs_mode(consumer)
    enable = marker_flex_enable(consumer)
    for io_name, value in values.items():
        name = str(io_name or "").strip()
        if not name:
            continue
        if current and name == current:
            kind = "set_evcs_max_current"
        elif mode and name == mode:
            kind = "set_evcs_mode"
        elif enable and name == enable:
            kind = "set_enable"
        else:
            continue
        qid = qualified_consumer_id(cid, ctype, kind)
        records.append(
            _publish_setpoint_traced(qid, float(value), io_name=name)
        )
    return records


def _write_flexible_consumer_output(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    snapshot: dict[str, float] | None,
    consumer_pv_follow: dict[str, int] | None = None,
    *,
    send: bool,
) -> list[LoxoneWriteRecord]:
    """Publishes Freigabe/Strom-Sollwert/Modus via status.json and/or snapshot."""
    values = _flexible_consumer_output_values(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    records: list[LoxoneWriteRecord] = []
    if send:
        records.extend(_publish_flexible_consumer_outputs(consumer, values))
    if snapshot is not None:
        snapshot.update(values)
    return records


_OMIT_EXPORT_CAP = object()


def _battery_max_powers_kw(battery_params: dict) -> tuple[float, float]:
    """(max charge kW, max discharge kW) from battery params; ``max_power_kw`` as shared cap."""
    max_charge = float(
        battery_params.get("max_charge_power_kw")
        or battery_params.get("max_power_kw")
        or 0.0
    )
    max_discharge = float(
        battery_params.get("max_discharge_power_kw")
        or battery_params.get("max_power_kw")
        or 0.0
    )
    return max_charge, max_discharge


def _export_cap_marker_and_value(
    export_cap_kw: float | None | object,
) -> tuple[str, float] | None:
    """Plant export-limit marker name and setpoint [kW]; None when no marker is bound."""
    from house_config.ehal_bindings import resolve_plant_binding
    from optimizer.export_power_limit import export_limit_setpoint_kw
    from optimizer.live_export_limit import (
        live_unconstrained_export_kw,
        load_house_doc,
    )

    export_marker = resolve_plant_binding(
        load_house_doc(), "set_grid_export_power_limit"
    )
    if not export_marker:
        return None
    cap = None if export_cap_kw is None else float(export_cap_kw)  # type: ignore[arg-type]
    value = float(
        export_limit_setpoint_kw(cap, unconstrained_kw=live_unconstrained_export_kw())
    )
    return str(export_marker), value


def build_sent_loxone_snapshot(
    mode: int,
    target_power_kw: float,
    target_soc: float,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None,
    consumer_pv_follow: dict[str, int] | None = None,
    *,
    export_cap_kw: float | None | object = _OMIT_EXPORT_CAP,
) -> dict[str, float]:
    """Alle an Loxone gesendeten Steuerwerte: Merkername → Zahl."""
    max_charge, max_discharge = _battery_max_powers_kw(config.get_battery_params())
    active_kw, charge_kw, discharge_kw, control_cmd = map_ess_setpoints(
        mode, target_power_kw, max_charge, max_discharge
    )
    contexts = charging_contexts or {}
    snapshot: dict[str, float] = {}
    # target_soc_name removed (2.4.j): ESS via active_power + limits + set_ess_mode.
    _ = target_soc

    from house_config.ess_bindings import resolve_primary_ess_binding
    from integrations.ehal_debug_mapping import has_mappable_live_batteries

    has_batteries = bool(has_mappable_live_batteries())
    for kind, value in (
        ("set_ess_active_power", active_kw),
        ("set_ess_charge_power_limit", charge_kw),
        ("set_ess_discharge_power_limit", discharge_kw),
        ("set_ess_mode", float(control_cmd)),
    ):
        wired = resolve_primary_ess_binding(kind)
        if not wired:
            continue
        if value is None:
            if kind != "set_ess_active_power":
                continue
            send_value = 0.0
        else:
            send_value = float(value)
        key = _ess_c1_exchange_field(
            kind, wired, {}, has_batteries=has_batteries
        ) or wired
        snapshot[key] = send_value

    if export_cap_kw is not _OMIT_EXPORT_CAP:
        export = _export_cap_marker_and_value(export_cap_kw)
        if export is not None:
            snapshot[export[0]] = export[1]

    for consumer in config.get_flexible_consumers(optimizer_only=True):
        _write_flexible_consumer_output(
            consumer, consumer_powers, contexts, snapshot, consumer_pv_follow, send=False
        )

    return snapshot


def _ess_c1_exchange_field(
    kind: str,
    cfg_name: str,
    io_to_field: dict[str, str],
    *,
    has_batteries: bool,
) -> str:
    """Resolve plant ESS Merker / activation name → publish EHAL id (Q8)."""
    from ehal.ess_fields import ess_field
    from integrations.ehal_debug_mapping import resolve_loxone_write_field
    from integrations.loxone_adapter import primary_ess_id_for_plant_read

    name = str(cfg_name or "").strip()
    if not name:
        return ""
    if has_batteries:
        bid = primary_ess_id_for_plant_read()
        return ess_field(bid, kind) if bid else ""
    field = str(io_to_field.get(name) or "").strip()
    if field:
        return field
    return str(resolve_loxone_write_field(name, io_to_field) or "").strip()


def send_huawei_modbus_states(
    mode: int,
    target_power_kw: float,
    target_soc: float,
    *,
    export_cap_kw: float | None | object = _OMIT_EXPORT_CAP,
) -> list[LoxoneWriteRecord]:
    """Übersetzt Optimierungsmodi und schreibt ESS-Steuerwerte (Design C1) an Loxone."""
    from house_config.battery_control import (
        BATTERY_CONTROL_LIMITS_ONLY,
        BATTERY_CONTROL_READ_ONLY,
        control_from_battery_params,
    )
    from integrations import loxone_client as lc

    battery_params = lc.config.get_battery_params()
    control = control_from_battery_params(battery_params)
    if control == BATTERY_CONTROL_READ_ONLY:
        return []

    max_charge, max_discharge = _battery_max_powers_kw(battery_params)
    if control == BATTERY_CONTROL_LIMITS_ONLY and mode in (1, 3):
        mode = 0
        target_power_kw = 0.0
    active_kw, charge_kw, discharge_kw, control_cmd = map_ess_setpoints(
        mode, target_power_kw, max_charge, max_discharge
    )
    if control == BATTERY_CONTROL_LIMITS_ONLY:
        active_kw = None
    # target_soc no longer written (2.4.j); kept in signature for call-site compat.
    _ = target_soc

    logger.info(
        "Sending ESS C1 Mapping -> Soll: %s kW, Ladegrenze: %s kW, "
        "Entladegrenze: %s kW, set_ess_mode/Cmd: %s",
        active_kw,
        charge_kw,
        discharge_kw,
        control_cmd,
    )

    records = _publish_ess_c1_setpoints(
        (
            ("set_ess_active_power", active_kw),
            ("set_ess_charge_power_limit", charge_kw),
            ("set_ess_discharge_power_limit", discharge_kw),
            ("set_ess_mode", float(control_cmd)),
        )
    )
    if export_cap_kw is not _OMIT_EXPORT_CAP:
        from ehal.qualified_ids import qualified_plant_id

        export = _export_cap_marker_and_value(export_cap_kw)
        if export is not None:
            records.append(
                _publish_setpoint_traced(
                    qualified_plant_id("set_grid_export_power_limit"),
                    export[1],
                    io_name=export[0],
                )
            )
    return records


def _publish_ess_c1_setpoints(
    kind_values: tuple[tuple[str, float | None], ...],
) -> list[LoxoneWriteRecord]:
    """Publish each wired ESS setpoint (kind, value) into the status.json ledger."""
    from house_config.ess_bindings import resolve_primary_ess_binding
    from integrations.ehal_debug_mapping import (
        build_loxone_setpoint_io_index,
        has_mappable_live_batteries,
    )

    records: list[LoxoneWriteRecord] = []
    io_to_field = build_loxone_setpoint_io_index()
    has_batteries = bool(has_mappable_live_batteries())
    active_wired = resolve_primary_ess_binding("set_ess_active_power")

    for kind, value in kind_values:
        wired = resolve_primary_ess_binding(kind)
        if not wired:
            continue
        if value is None:
            # Sticky VI: still refresh Sollleistung with 0 under Automatik/Entladesperre.
            if kind != "set_ess_active_power" or not active_wired:
                continue
            send_value = 0.0
        else:
            send_value = float(value)
        field = _ess_c1_exchange_field(
            kind, wired, io_to_field, has_batteries=has_batteries
        )
        if not field:
            logger.warning(
                "ESS C1: no EHAL field for binding %s — skip publish", wired
            )
            continue
        # Trace/Live-Schreiben key = exchange id (entity-scoped when batteries exist).
        records.append(_publish_setpoint_traced(field, send_value, io_name=field))
    return records


def write_inv_ac_power_limits(fields_w: dict[str, float]) -> list[LoxoneWriteRecord]:
    """Publish ``inv.{id}.set_inv_ac_power_limit`` (EHAL W → Loxone kW) to status.json."""
    from ehal.field_registry import require_loxone_write
    from ehal.inverter_fields import inv_field_kind

    records: list[LoxoneWriteRecord] = []
    for qualified_id, value_w in (fields_w or {}).items():
        qid = str(qualified_id or "").strip()
        if not qid or inv_field_kind(qid) != "set_inv_ac_power_limit":
            continue
        hub_kw = float(require_loxone_write("set_inv_ac_power_limit", float(value_w)))
        records.append(_publish_setpoint_traced(qid, hub_kw, io_name=qid))
    return records


def send_flexible_consumer_states(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> list[LoxoneWriteRecord]:
    """Sendet Freigabe (0/1), set_evcs_max_current (A) und set_evcs_mode an Loxone."""
    contexts = charging_contexts or {}
    records: list[LoxoneWriteRecord] = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        records.extend(
            _write_flexible_consumer_output(
                consumer, consumer_powers, contexts, None, consumer_pv_follow, send=True
            )
        )
    return records


