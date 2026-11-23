"""Loxone write helpers: setpoints, ESS, flexible consumer outputs.

Import facade: the ESS C1 setpoint math lives in ``integrations.loxone_ess_setpoints``
and the flexible consumer output values in ``integrations.loxone_flex_outputs``; both
are re-exported here. Publishing (``_publish_setpoint_traced``) and the send paths stay
in this module, so patches on ``integrations.loxone_writes.<name>`` reach them. A name that
moved to a sibling is looked up there: patch it in the sibling (see
``.cursor/rules/import-facades.mdc``).
"""
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
    marker_set_sg_ready_state,
    marker_set_store_target,
)
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere  # noqa: F401
from settings.flexible_consumers import runtime_consumer_id  # noqa: F401

logger = logging.getLogger(__name__)

from integrations.loxone_ess_setpoints import (  # noqa: E402,F401  (re-exports)
    TARGET_SOC_POWER_SHARE,
    TARGET_SOC_REPORT_STEP_PCT,
    _OMIT_EXPORT_CAP,
    _battery_max_powers_kw,
    _ess_battery_params,
    _ess_c1_exchange_field,
    _export_cap_marker_and_value,
    ess_c1_kind_values,
    ess_target_soc_buffer_percent,
    ess_target_soc_percent,
    map_ess_setpoints,
)
from integrations.loxone_flex_outputs import (  # noqa: E402,F401  (re-exports)
    _EVCS_MODE_VALUES,
    _append_evcs_mode_writes,
    _effective_consumer_power_kw,
    _enable_output_values,
    _evcs_current_output_values,
    _flexible_consumer_output_values,
    _immediate_skip_output_values,
    _sg_ready_state_output_values,
    _skip_flexible_consumer_output,
    _store_target_output_values,
    flex_consumer_enable_value,
    flex_consumer_power_setpoint_kw,
    flex_consumer_setpoint_amps,
)


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
    from runtime_store.shadow.hooks import block_write_if_shadow

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



def _publish_flexible_consumer_outputs(
    consumer: dict,
    values: dict[str, float],
    *,
    kinds: frozenset[str] | None = None,
) -> list[LoxoneWriteRecord]:
    """Publish qualified IDs for flex/EV outputs (2.7.q Q5 push-only).

    ``kinds`` restricts the publish to those field kinds (``None`` = all).
    """
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
    sg_state = marker_set_sg_ready_state(consumer)
    store_target = marker_set_store_target(consumer)
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
        elif sg_state and name == sg_state:
            kind = "set_sg_ready_state"
        elif store_target and name == store_target:
            kind = "set_temperature_heat_storage_target"
        else:
            continue
        if kinds is not None and kind not in kinds:
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
    publish_kinds: frozenset[str] | None = None,
    heat_storage_targets: dict[str, float] | None = None,
    heat_forced_charge: frozenset[str] | None = None,
) -> list[LoxoneWriteRecord]:
    """Publishes Freigabe/Strom-Sollwert/Modus via status.json and/or snapshot."""
    values = _flexible_consumer_output_values(
        consumer,
        consumer_powers,
        charging_contexts,
        consumer_pv_follow,
        heat_storage_targets=heat_storage_targets,
        heat_forced_charge=heat_forced_charge,
    )
    records: list[LoxoneWriteRecord] = []
    if send:
        records.extend(
            _publish_flexible_consumer_outputs(consumer, values, kinds=publish_kinds)
        )
    if snapshot is not None:
        snapshot.update(values)
    return records


def build_sent_loxone_snapshot(
    mode: int,
    target_power_kw: float,
    target_soc: float,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None,
    consumer_pv_follow: dict[str, int] | None = None,
    *,
    export_cap_kw: float | None | object = _OMIT_EXPORT_CAP,
    automatik_discharge_cap_kw: float | None = None,
    battery_params: dict | None = None,
) -> dict[str, float]:
    """Alle an Loxone gesendeten Steuerwerte: Merkername → Zahl.

    ``battery_params``: same effective params as ``send_huawei_modbus_states`` got in
    this cycle, so the ledger matches what was sent (see ``_ess_battery_params``).
    """
    battery_params = _ess_battery_params(battery_params, config)
    contexts = charging_contexts or {}
    snapshot: dict[str, float] = {}

    from house_config.ess_bindings import resolve_primary_ess_binding
    from integrations.ehal_debug_mapping import has_mappable_live_batteries

    has_batteries = bool(has_mappable_live_batteries())
    kind_values = ess_c1_kind_values(
        mode,
        target_power_kw,
        target_soc,
        battery_params,
        automatik_discharge_cap_kw=automatik_discharge_cap_kw,
    )
    for kind, value in kind_values:
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

    # Same gate as send_huawei_modbus_states: read_only (no ESS values) sends no
    # export cap either, so the ledger must not expect one.
    if kind_values and export_cap_kw is not _OMIT_EXPORT_CAP:
        export = _export_cap_marker_and_value(export_cap_kw)
        if export is not None:
            snapshot[export[0]] = export[1]

    for consumer in config.get_flexible_consumers(optimizer_only=True):
        _write_flexible_consumer_output(
            consumer, consumer_powers, contexts, snapshot, consumer_pv_follow, send=False
        )

    return snapshot


def send_huawei_modbus_states(
    mode: int,
    target_power_kw: float,
    target_soc: float,
    *,
    export_cap_kw: float | None | object = _OMIT_EXPORT_CAP,
    automatik_discharge_cap_kw: float | None = None,
    battery_params: dict | None = None,
) -> list[LoxoneWriteRecord]:
    """Übersetzt Optimierungsmodi und schreibt ESS-Steuerwerte (Design C1) an Loxone.

    ``battery_params``: the effective params the plan used (live limits applied);
    ``None`` uses the house config limits (see ``_ess_battery_params``).
    """
    from integrations import loxone_client as lc

    battery_params = _ess_battery_params(battery_params, lc.config)
    kind_values = ess_c1_kind_values(
        mode,
        target_power_kw,
        target_soc,
        battery_params,
        automatik_discharge_cap_kw=automatik_discharge_cap_kw,
    )
    if not kind_values:
        return []

    sent = dict(kind_values)
    logger.info(
        "Sending ESS C1 Mapping -> Soll: %s kW, Ladegrenze: %s kW, "
        "Entladegrenze: %s kW, set_ess_mode/Cmd: %s, Ziel-SoC: %s %%",
        sent["set_ess_active_power"],
        sent["set_ess_charge_power_limit"],
        sent["set_ess_discharge_power_limit"],
        sent["set_ess_mode"],
        sent["set_ess_target_soc"],
    )

    records = _publish_ess_c1_setpoints(kind_values)
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
    *,
    heat_storage_targets: dict[str, float] | None = None,
    heat_forced_charge: frozenset[str] | None = None,
) -> list[LoxoneWriteRecord]:
    """Sendet Freigabe (0/1), set_evcs_max_current (A) und set_evcs_mode an Loxone.

    ``heat_storage_targets``: store charge target per heat pump (HeatControl P3); ``None``
    writes no target, a missing heat pump in the dict gets 0 (no target).
    """
    contexts = charging_contexts or {}
    records: list[LoxoneWriteRecord] = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        records.extend(
            _write_flexible_consumer_output(
                consumer,
                consumer_powers,
                contexts,
                None,
                consumer_pv_follow,
                send=True,
                heat_storage_targets=heat_storage_targets,
                heat_forced_charge=heat_forced_charge,
            )
        )
    return records


def send_flexible_consumer_enables(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
    *,
    heat_storage_targets: dict[str, float] | None = None,
    heat_forced_charge: frozenset[str] | None = None,
) -> list[LoxoneWriteRecord]:
    """Publish only the flex ``set_enable`` (heat pump, pool, generic consumers), the
    heat pump's ``set_sg_ready_state`` (HeatControl P2) and its store charge target (P3).

    For the HA backend: the EV current is written through the EVCS adapter
    (``ehal_live.write_evcs_max_current_from_consumers``), so it is not published a
    second time here.
    """
    contexts = charging_contexts or {}
    records: list[LoxoneWriteRecord] = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        records.extend(
            _write_flexible_consumer_output(
                consumer,
                consumer_powers,
                contexts,
                None,
                consumer_pv_follow,
                send=True,
                publish_kinds=frozenset(
                    {"set_enable", "set_sg_ready_state", "set_temperature_heat_storage_target"}
                ),
                heat_storage_targets=heat_storage_targets,
                heat_forced_charge=heat_forced_charge,
            )
        )
    return records


