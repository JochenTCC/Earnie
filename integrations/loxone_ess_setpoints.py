"""ESS C1 setpoint math for the Loxone/EHAL write path (no publishing).

Split from ``integrations.loxone_writes`` (2.8 quality gate); that module stays the
import facade and re-exports every name defined here.
"""
from __future__ import annotations

import logging
import math

# Same logger name as before the split, so log filters and captures stay unchanged.
logger = logging.getLogger("integrations.loxone_writes")


def map_ess_setpoints(
    mode: int,
    target_power_kw: float,
    max_charge_power_kw: float,
    max_discharge_power_kw: float | None = None,
    *,
    automatik_discharge_cap_kw: float | None = None,
) -> tuple[float | None, float, float, int]:
    """Design C1: (active_power_kw|None, charge_limit_kw, discharge_limit_kw, mode_hint).

    ``active_power_kw`` uses EHAL sign (+discharge, −charge). ``None`` means Automatik /
    Entladesperre without a forced Equals setpoint. Limits are true caps (kW magnitudes).
    ``mode_hint`` is for Loxone/HA (Huawei Steuerbefehl); OpenEMS ignores it.
    Battery-only: export caps travel on ``set_grid_export_power_limit`` (2.7.a).

    ``max_discharge_power_kw`` defaults to ``max_charge_power_kw`` for legacy single-max
    callers (pre-2.7.j). ``automatik_discharge_cap_kw`` caps the discharge limit in
    Automatik only (virtual reserve floor, ``reserve_floor_discharge_cap_kw``).
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
    if automatik_discharge_cap_kw is not None:
        max_discharge = min(max_discharge, max(0.0, float(automatik_discharge_cap_kw)))
    return None, max_charge, max_discharge, 0


# Inverters such as the Huawei LUNA report SoC in whole percent and end a forced
# charge/discharge when that reported value reaches the target. A target with decimals
# can stop the slot up to one step early, so forced modes get a buffer beyond the plan's
# slot-end SoC: one reporting step plus a share of the SoC change the slot plans at the
# target power (faster slots overshoot the reporting step more before the stop). The
# active power setpoint still bounds the energy of the slot; the next cycle re-plans.
TARGET_SOC_REPORT_STEP_PCT = 1.0
TARGET_SOC_POWER_SHARE = 0.25


def ess_target_soc_buffer_percent(
    mode: int,
    target_power_kw: float,
    battery_capacity_kwh: float,
    *,
    dt_h: float,
) -> float:
    """SoC buffer (%) beyond the planned slot-end SoC for forced charge/discharge.

    0 for Automatik and hold (Entladesperre): hold sends the current SoC as target
    and must not charge or discharge past it.
    """
    if mode not in (1, 3):  # MODE_ZWANGS_LADEN, MODE_ZWANGS_ENTLADEN
        return 0.0
    power = abs(float(target_power_kw))
    if power <= 0.0:
        return 0.0
    capacity = float(battery_capacity_kwh)
    if capacity <= 0.0:
        raise ValueError(
            f"set_ess_target_soc: battery capacity {capacity} kWh, buffer needs a capacity > 0"
        )
    slot_soc_change_pct = power * float(dt_h) / capacity * 100.0
    return TARGET_SOC_REPORT_STEP_PCT + TARGET_SOC_POWER_SHARE * slot_soc_change_pct


def ess_target_soc_percent(
    target_soc: float,
    *,
    mode: int,
    target_power_kw: float,
    battery_params: dict,
) -> float:
    """Target SoC for ``set_ess_target_soc`` in % (0-100, one decimal).

    The optimizer's value per mode: hold (Entladesperre) = current SoC, forced
    charge/discharge = planned SoC at slot end, Automatik = 99. Forced modes move it
    by ``ess_target_soc_buffer_percent`` (down for discharge, up for charge), never
    past the battery's ``min_soc`` / ``max_soc``. Only written when the battery maps
    ``set_ess_target_soc``.
    """
    from optimizer.slot_duration import DEFAULT_DT_H

    value = float(target_soc)
    if math.isnan(value):
        raise ValueError("set_ess_target_soc: target SoC is NaN")
    if mode in (1, 3) and abs(float(target_power_kw)) > 0.0:
        buffer = ess_target_soc_buffer_percent(
            mode,
            target_power_kw,
            float(battery_params["battery_capacity_kwh"]),
            dt_h=DEFAULT_DT_H,
        )
        # The clamp only limits the buffer; it never moves the plan's own value back.
        if mode == 3:
            value = min(value, max(float(battery_params["min_soc"]), value - buffer))
        else:
            value = max(value, min(float(battery_params["max_soc"]), value + buffer))
    return round(min(100.0, max(0.0, value)), 1)


_OMIT_EXPORT_CAP = object()


def _battery_max_powers_kw(battery_params: dict) -> tuple[float, float]:
    """(max charge kW, max discharge kW) from battery params.

    An explicit value wins, also 0 (charge/discharge disabled or derated to 0 by the
    live limits). ``max_power_kw`` is only the shared cap when a direction is not set.
    A battery without any max power raises: publishing 0/0 would block the battery.
    """
    shared = battery_params.get("max_power_kw")

    def _pick(key: str) -> float:
        value = battery_params.get(key)
        if value is None:
            value = shared
        if value is None:
            raise ValueError(
                f"ESS C1: battery {battery_params.get('id') or '?'!s} has no {key} "
                "and no max_power_kw — refusing to publish a power limit"
            )
        return float(value)

    return _pick("max_charge_power_kw"), _pick("max_discharge_power_kw")


def _ess_battery_params(battery_params: dict | None, source) -> dict:
    """Battery params for the ESS C1 setpoints.

    ``battery_params`` are the effective params the plan used (live ``get_ess_max_*``
    applied, ``settings.ess_limits_resolve``). ``None`` means no telemetry is at hand
    (startup safe push, watchdog rebuild without ``loxone_sent``): the house config
    limits are used, and the log says so.
    """
    if battery_params is not None:
        return battery_params
    logger.info("ESS C1: Grenzen aus der Hauskonfiguration (keine Live-Limits übergeben)")
    return source.get_battery_params()


def ess_c1_kind_values(
    mode: int,
    target_power_kw: float,
    target_soc: float,
    battery_params: dict,
    *,
    automatik_discharge_cap_kw: float | None = None,
) -> tuple[tuple[str, float | None], ...]:
    """ESS C1 setpoints (kind, value) Earnie sends for this battery control level.

    Single source for the live send path (``send_huawei_modbus_states``) and the
    ``loxone_sent`` ledger (``build_sent_loxone_snapshot``), so both stay identical:

    - ``read_only``: no ESS setpoint at all (empty tuple).
    - ``limits_only``: forced charge/discharge (modes 1/3) fall back to Automatik
      (mode 0, power 0) and no active power setpoint is forced (``None``); the target
      SoC is computed for the reduced mode.
    - ``full``: the optimizer mode as mapped by ``map_ess_setpoints``.

    ``None`` as value means "no forced setpoint" (callers send 0 on a wired active
    power binding and skip the other kinds).
    """
    from house_config.battery_control import (
        BATTERY_CONTROL_LIMITS_ONLY,
        BATTERY_CONTROL_READ_ONLY,
        control_from_battery_params,
    )

    control = control_from_battery_params(battery_params)
    if control == BATTERY_CONTROL_READ_ONLY:
        return ()

    max_charge, max_discharge = _battery_max_powers_kw(battery_params)
    if control == BATTERY_CONTROL_LIMITS_ONLY and mode in (1, 3):
        mode = 0
        target_power_kw = 0.0
    active_kw, charge_kw, discharge_kw, control_cmd = map_ess_setpoints(
        mode,
        target_power_kw,
        max_charge,
        max_discharge,
        automatik_discharge_cap_kw=automatik_discharge_cap_kw,
    )
    if control == BATTERY_CONTROL_LIMITS_ONLY:
        active_kw = None
    target_soc_pct = ess_target_soc_percent(
        target_soc,
        mode=mode,
        target_power_kw=target_power_kw,
        battery_params=battery_params,
    )
    return (
        ("set_ess_active_power", active_kw),
        ("set_ess_charge_power_limit", charge_kw),
        ("set_ess_discharge_power_limit", discharge_kw),
        ("set_ess_mode", float(control_cmd)),
        ("set_ess_target_soc", target_soc_pct),
    )


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
