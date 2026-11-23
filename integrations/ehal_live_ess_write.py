"""ESS Design C1 setpoint writes for OpenEMS/HA (split from ``ehal_live``).

Late-bound through ``integrations.ehal_live`` (``live``) so patches applied to the
façade (``config``, adapters, backend checks, ``map_ess_setpoints``, ...) stay effective.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ehal import EHAL_SCHEMA_VERSION, EhalWriteError
from integrations.ehal_live_ref import live

_OMIT_EXPORT_CAP = object()


def _control_ess_setpoints(
    control: str,
    mode: int,
    target_power_kw: float,
    max_charge_kw: float,
    max_discharge_kw: float,
    automatik_discharge_cap_kw: float | None = None,
) -> tuple[float | None, float, float, int]:
    """``map_ess_setpoints`` honouring limits-only battery control (no active power)."""
    from house_config.battery_control import BATTERY_CONTROL_LIMITS_ONLY

    active_kw, charge_kw, discharge_kw, control_cmd = live.map_ess_setpoints(
        mode,
        target_power_kw,
        max_charge_kw,
        max_discharge_kw,
        automatik_discharge_cap_kw=automatik_discharge_cap_kw,
    )
    if control == BATTERY_CONTROL_LIMITS_ONLY:
        active_kw = None
        if mode in (1, 3):
            active_kw, charge_kw, discharge_kw, control_cmd = live.map_ess_setpoints(
                0,
                0.0,
                max_charge_kw,
                max_discharge_kw,
                automatik_discharge_cap_kw=automatik_discharge_cap_kw,
            )
    return active_kw, charge_kw, discharge_kw, control_cmd


def _build_ess_setpoint_docs(
    adapter_id: str,
    ts: str,
    ess_values: tuple[float | None, float, float, int],
    export_cap_kw: float | None | object,
) -> tuple[dict[str, Any], dict[str, float]]:
    """EHAL setpoint doc (W) and the matching write-record field map."""
    from optimizer.export_power_limit import export_limit_setpoint_w
    from optimizer.live_export_limit import live_unconstrained_export_kw

    active_kw, charge_kw, discharge_kw, control_cmd = ess_values
    charge_w = max(0.0, float(charge_kw) * 1000.0)
    discharge_w = max(0.0, float(discharge_kw) * 1000.0)
    setpoint: dict[str, Any] = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter_id,
        "set_ess_charge_power_limit": charge_w,
        "set_ess_discharge_power_limit": discharge_w,
        "set_ess_mode": control_cmd,
    }
    record_fields: dict[str, float] = {
        "set_ess_charge_power_limit": charge_w,
        "set_ess_discharge_power_limit": discharge_w,
        "set_ess_mode": float(control_cmd),
    }
    if active_kw is not None:
        active_w = float(active_kw) * 1000.0
        setpoint["set_ess_active_power"] = active_w
        record_fields["set_ess_active_power"] = active_w
    if export_cap_kw is not _OMIT_EXPORT_CAP:
        cap = None if export_cap_kw is None else float(export_cap_kw)  # type: ignore[arg-type]
        limit_w = export_limit_setpoint_w(
            cap, unconstrained_kw=live_unconstrained_export_kw()
        )
        setpoint["set_grid_export_power_limit"] = limit_w
        record_fields["set_grid_export_power_limit"] = limit_w
    return setpoint, record_fields


def _resolve_ess_max_powers_kw(
    battery_params: dict,
    max_power_kw: float | None,
    max_charge_power_kw: float | None,
    max_discharge_power_kw: float | None,
) -> tuple[float, float]:
    """(max charge kW, max discharge kW): explicit args, else shared max, else params."""
    if max_charge_power_kw is None and max_discharge_power_kw is None and max_power_kw is not None:
        max_charge_power_kw = float(max_power_kw)
        max_discharge_power_kw = float(max_power_kw)
    if max_charge_power_kw is None:
        max_charge_power_kw = float(battery_params.get("max_charge_power_kw") or 0.0)
    if max_discharge_power_kw is None:
        max_discharge_power_kw = float(
            battery_params.get("max_discharge_power_kw") or 0.0
        )
    return float(max_charge_power_kw), float(max_discharge_power_kw)


def _ess_target_soc_value(
    target_soc: float,
    *,
    control: str,
    mode: int,
    target_power_kw: float,
    battery_params: dict,
) -> float:
    """``set_ess_target_soc`` (%) for the mode actually written."""
    from integrations.loxone_writes import ess_target_soc_percent

    from house_config.battery_control import BATTERY_CONTROL_LIMITS_ONLY

    # limits_only drops forced modes (``_control_ess_setpoints``): no buffer then.
    target_mode = (
        0 if control == BATTERY_CONTROL_LIMITS_ONLY and mode in (1, 3) else mode
    )
    return ess_target_soc_percent(
        target_soc,
        mode=target_mode,
        target_power_kw=target_power_kw,
        battery_params=battery_params,
    )


def _ess_write_records(
    adapter: Any,
    record_fields: dict[str, float],
    ts: str,
    error: EhalWriteError | None,
) -> list[dict[str, Any]]:
    """Persist a write error and build the ``ehal_writes`` trace rows."""
    if error is not None:
        live.persist_write_error(error)
    from integrations.ehal_live_records import _last_skipped_messages

    return live.build_ehal_write_records(
        record_fields,
        written_at=ts,
        error=error,
        skipped=live._last_skipped(adapter),
        unconfigured=live._last_unconfigured(adapter),
        skipped_messages=_last_skipped_messages(adapter),
    )


def write_ess_setpoints_from_control(
    mode: int,
    target_power_kw: float,
    max_power_kw: float | None = None,
    *,
    max_charge_power_kw: float | None = None,
    max_discharge_power_kw: float | None = None,
    export_cap_kw: float | None | object = _OMIT_EXPORT_CAP,
    telemetry: dict[str, Any] | None = None,
    automatik_discharge_cap_kw: float | None = None,
    target_soc: float | None = None,
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Map optimizer mode/power to EHAL Design C1 ESS setpoints.

    ``automatik_discharge_cap_kw`` caps the discharge limit in Automatik (virtual reserve floor).
    ``target_soc`` (optimizer target SoC in %) adds ``set_ess_target_soc``; the adapter
    writes it only where the battery activates that field.

    When ``export_cap_kw`` is passed (including ``None`` = unconstrained), also write
    ``set_grid_export_power_limit`` (W magnitude; plant export maximum = PV kWp + force
    discharge kW when unconstrained, see ``live_unconstrained_export_kw``).
    """
    from house_config.battery_control import (
        BATTERY_CONTROL_FULL,
        BATTERY_CONTROL_READ_ONLY,
        control_from_battery_params,
    )
    from settings.ess_limits_resolve import apply_effective_ess_limits

    battery_params = apply_effective_ess_limits(
        live.config.get_battery_params(), telemetry=telemetry
    )
    control = control_from_battery_params(battery_params)
    if control == BATTERY_CONTROL_READ_ONLY:
        return None, []

    max_charge_kw, max_discharge_kw = _resolve_ess_max_powers_kw(
        battery_params, max_power_kw, max_charge_power_kw, max_discharge_power_kw
    )
    active_kw, charge_kw, discharge_kw, control_cmd = live._control_ess_setpoints(
        control,
        mode,
        target_power_kw,
        max_charge_kw,
        max_discharge_kw,
        automatik_discharge_cap_kw,
    )
    if active_kw is None and live.is_ha_backend() and control == BATTERY_CONTROL_FULL:
        # The HA ``number`` is sticky: omitting the active power would leave the last force
        # in place (L18). 0 W is the release the HA force automation understands.
        active_kw = 0.0
    adapter = live.get_network_adapter()
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    setpoint, record_fields = live._build_ess_setpoint_docs(
        adapter.cfg.adapter_id,
        ts,
        (active_kw, charge_kw, discharge_kw, control_cmd),
        export_cap_kw,
    )
    if target_soc is not None:
        target_soc_pct = _ess_target_soc_value(
            target_soc,
            control=control,
            mode=mode,
            target_power_kw=target_power_kw,
            battery_params=battery_params,
        )
        setpoint["set_ess_target_soc"] = target_soc_pct
        record_fields["set_ess_target_soc"] = target_soc_pct
    error = adapter.write_setpoints(setpoint)
    return error, _ess_write_records(adapter, record_fields, ts, error)
