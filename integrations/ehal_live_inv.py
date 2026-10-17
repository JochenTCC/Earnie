"""Per-inverter AC power limit writes (split from ``ehal_live``).

Late-bound through ``integrations.ehal_live`` (``live``) so patches applied to
the façade (``config``, adapters, backend checks, ...) stay effective.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ehal import EhalWriteError
from integrations.ehal_live_ref import live

# Keep the historic logger name so log filters keep working after the split.
logger = logging.getLogger("integrations.ehal_live")


def _planning_inverters() -> list[dict]:
    raw = getattr(live.config, "_planning_inverters", None)
    if raw is None and hasattr(live.config, "get"):
        try:
            raw = live.config.get("_planning_inverters", None)
        except TypeError:
            raw = None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _planning_pv_systems() -> list[dict]:
    raw = getattr(live.config, "_planning_pv_systems", None)
    if raw is None and hasattr(live.config, "get"):
        try:
            raw = live.config.get("_planning_pv_systems", None)
        except TypeError:
            raw = None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _mapped_inv_limit_ids() -> set[str]:
    """Inverter ids with a non-empty ``set_inv_ac_power_limit`` binding."""
    from ehal.inverter_fields import binding_address, inv_field

    mapped: set[str] = set()
    for inv in _planning_inverters():
        inv_id = str(inv.get("id") or "").strip()
        if not inv_id:
            continue
        bindings = inv.get("ehal_bindings")
        bind_map = bindings if isinstance(bindings, dict) else {}
        addr = binding_address(bind_map, inv_id, "set_inv_ac_power_limit")
        field = inv_field(inv_id, "set_inv_ac_power_limit")
        if not addr and field in bind_map:
            addr = str(bind_map.get(field) or "").strip()
        if not addr:
            continue
        if live.is_openems_backend() and live._openems_channel_parts(addr) is None:
            continue
        mapped.add(inv_id)
    return mapped


def _battery_params_for_inv_limits() -> list[dict]:
    get_list = getattr(live.config, "get_battery_params_list", None)
    if callable(get_list):
        return [b for b in (get_list() or []) if isinstance(b, dict)]
    bat = live.config.get_battery_params()
    return [bat] if isinstance(bat, dict) else []


def _inv_limit_fields_w(
    *,
    plant_curtail_kw: float,
    matrix_row: dict[str, Any] | None,
    milp_plan: dict[str, Any] | None,
) -> dict[str, float]:
    """Qualified ``inv.{id}.set_inv_ac_power_limit`` → EHAL W for writable inverters."""
    from ehal.inverter_fields import inv_field
    from optimizer.inv_ac_power_limit import (
        allocate_inv_ac_limits_kw,
        eligible_inv_limit_ids,
        force_discharge_kw_by_inverter,
        inv_ac_limit_setpoint_w,
        planned_discharge_kw_by_inverter,
        pv_kwp_by_inverter,
    )

    inverters = _planning_inverters()
    if not inverters:
        return {}
    writable = eligible_inv_limit_ids(inverters, mapped_ids=_mapped_inv_limit_ids())
    if not writable:
        return {}
    pv_systems = _planning_pv_systems()
    batteries = _battery_params_for_inv_limits()
    limits_kw = allocate_inv_ac_limits_kw(
        inverters=inverters,
        writable_ids=writable,
        plant_curtail_kw=float(plant_curtail_kw or 0.0),
        matrix_row=matrix_row if isinstance(matrix_row, dict) else {},
        pv_systems=pv_systems,
        pv_kwp_by_inverter=pv_kwp_by_inverter(pv_systems),
        force_discharge_kw_by_inverter=force_discharge_kw_by_inverter(batteries),
        planned_discharge_by_inverter=planned_discharge_kw_by_inverter(
            milp_plan, battery_params=batteries
        ),
    )
    return {
        inv_field(inv_id, "set_inv_ac_power_limit"): inv_ac_limit_setpoint_w(limit_kw)
        for inv_id, limit_kw in limits_kw.items()
    }


def write_inv_ac_limits_from_plan(
    *,
    plant_curtail_kw: float = 0.0,
    matrix_row: dict[str, Any] | None = None,
    milp_plan: dict[str, Any] | None = None,
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Write per-inverter AC limits (P5 curtail-only sticky loop)."""
    fields_w = _inv_limit_fields_w(
        plant_curtail_kw=plant_curtail_kw,
        matrix_row=matrix_row,
        milp_plan=milp_plan,
    )
    if not fields_w:
        return None, []

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if live.is_ehal_network_backend():
        adapter = live.get_network_adapter()
        writer = getattr(adapter, "write_mapped_fields", None)
        if not callable(writer):
            logger.warning(
                "EHAL: adapter has no write_mapped_fields — skip inverter AC limits"
            )
            return None, []
        error = writer(fields_w)
        if error is not None:
            live.persist_write_error(error)
        return error, live.build_ehal_write_records(
            fields_w,
            written_at=ts,
            error=error,
            skipped=live._last_skipped(adapter),
        )

    from integrations.loxone_writes import write_inv_ac_power_limits

    records = write_inv_ac_power_limits(fields_w)
    rows = [
        {
            "field": getattr(row, "io_name", ""),
            "value": float(getattr(row, "value", 0.0) or 0.0),
            "success": bool(getattr(row, "success", False)),
            "written_at": str(getattr(row, "written_at", ts) or ts),
            "message": "",
        }
        for row in records
    ]
    return None, rows
