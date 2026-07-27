"""Thin Live façade: OpenEMS EHAL backend vs legacy Loxone path."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import config
from ehal import EHAL_SCHEMA_VERSION, EhalWriteError, validate_write_error
from integrations import loxone_client
from integrations.openems_adapter import OpenemsAdapter, OpenemsConfig, OpenemsHttpError
from runtime_store.persist_paths import runtime_path
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere

logger = logging.getLogger(__name__)

WRITE_ERROR_FILENAME = "ehal_write_error.json"

_adapter: OpenemsAdapter | None = None


def is_openems_backend() -> bool:
    return str(config.get("EHAL_BACKEND") or "").strip().lower() == "openems"


def write_error_path() -> str:
    return runtime_path(WRITE_ERROR_FILENAME)


def persist_write_error(error: EhalWriteError | None) -> None:
    path = write_error_path()
    if error is None:
        clear_write_error()
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(dict(error), handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def clear_write_error() -> None:
    path = write_error_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError as exc:
            logger.warning("Could not clear EHAL write error file: %s", exc)


def load_write_error() -> EhalWriteError | None:
    path = write_error_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return validate_write_error(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Invalid EHAL write error file %s: %s", path, exc)
        return None


def get_openems_adapter() -> OpenemsAdapter:
    global _adapter
    base_url = str(config.get("EHAL_OPENEMS_BASE_URL") or "").strip()
    if not base_url:
        raise ValueError(
            "ehal.backend=openems requires ehal.openems.base_url "
            "(EHAL_OPENEMS_BASE_URL)."
        )
    cfg = OpenemsConfig(
        base_url=base_url,
        username=str(config.get("EHAL_OPENEMS_USERNAME") or "x"),
        password=str(config.get("EHAL_OPENEMS_PASSWORD") or "admin"),
        adapter_id=str(config.get("EHAL_ADAPTER_ID") or "openems-lab"),
        ess_component=str(config.get("EHAL_OPENEMS_ESS_COMPONENT") or "ess0"),
        evcs_component=str(config.get("EHAL_OPENEMS_EVCS_COMPONENT") or "evcs0"),
        timeout_sec=float(config.get("GLOBAL_TIMEOUT") or 10),
    )
    if _adapter is not None and _adapter.cfg != cfg:
        _adapter = None
    if _adapter is None:
        _adapter = OpenemsAdapter(cfg)
    return _adapter


def reset_adapter_cache() -> None:
    """Test helper: drop cached adapter instance."""
    global _adapter
    _adapter = None


def read_ess_soc() -> float | None:
    if not is_openems_backend():
        return loxone_client.fetch_loxone_generic_value(config.get("LOXONE_SOC_NAME"))
    try:
        telemetry = get_openems_adapter().read_telemetry()
    except (OpenemsHttpError, ValueError, OSError) as exc:
        logger.error("EHAL/OpenEMS SoC read failed: %s", exc)
        return None
    return float(telemetry["ess_soc"])


def read_live_power_kw() -> dict[str, float] | None:
    """Return Live power dict (kW) in Loxone-compatible signs (+ battery = charge)."""
    if not is_openems_backend():
        return loxone_client.fetch_loxone_live_power()
    try:
        telemetry = get_openems_adapter().read_telemetry()
    except (OpenemsHttpError, ValueError, OSError) as exc:
        logger.error("EHAL/OpenEMS live power read failed: %s", exc)
        return None

    pv = max(0.0, float(telemetry["pv_production_active"]) / 1000.0)
    grid = float(telemetry["grid_power_active"]) / 1000.0
    ess_w = telemetry.get("ess_power")
    if ess_w is None:
        battery = 0.0
    else:
        # EHAL ess_power: +discharge; Live/Loxone convention: +charge
        battery = -float(ess_w) / 1000.0
    house = pv + battery + grid
    return {
        "pv": round(pv, 2),
        "house": round(house, 2),
        "battery": round(battery, 2),
        "grid": round(grid, 2),
    }


def write_ess_limits_from_huawei(mode: int, target_power_kw: float) -> EhalWriteError | None:
    """Map Huawei-style mode/power to EHAL ESS limits (skip target_soc / control_cmd)."""
    charge_kw, discharge_kw, _cmd = loxone_client.map_huawei_modbus_values(
        mode, target_power_kw
    )
    adapter = get_openems_adapter()
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    setpoint: dict[str, Any] = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter.cfg.adapter_id,
        "set_ess_charge_power_limit": max(0.0, float(charge_kw) * 1000.0),
        "set_ess_discharge_power_limit": max(0.0, float(discharge_kw) * 1000.0),
    }
    error = adapter.write_setpoints(setpoint)
    if error is not None:
        persist_write_error(error)
    return error


def write_evcs_max_current_from_consumers(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
) -> EhalWriteError | None:
    """Write set_evcs_max_current from first EV consumer planned power (kW→A)."""
    consumer = _first_ev_consumer()
    if consumer is None:
        logger.info("OpenEMS EHAL: no EV consumer configured — skip EVCS setpoint")
        return None

    cid = consumer["id"]
    planned_kw = max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0))
    ctx = (charging_contexts or {}).get(cid)
    if ctx is not None and not ctx.get("active", True):
        planned_kw = 0.0
    if ctx is not None and ctx.get("anticipated") and not ctx.get("plugged_in"):
        planned_kw = 0.0

    voltage_v, phases = ev_nominal_power_conversion(consumer)
    amps = kw_to_ampere(planned_kw, voltage_v=voltage_v, phases=phases)
    adapter = get_openems_adapter()
    if not adapter.capabilities()["supports_evcs_current"]:
        logger.info("OpenEMS EHAL: supports_evcs_current=false — skip EVCS write")
        return None

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    setpoint = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter.cfg.adapter_id,
        "set_evcs_max_current": max(0.0, amps),
    }
    error = adapter.write_setpoints(
        setpoint, evcs_voltage_v=voltage_v, evcs_phases=phases
    )
    if error is not None:
        persist_write_error(error)
    return error


def _first_ev_consumer() -> dict | None:
    for consumer in config.get_flexible_consumers():
        if consumer.get("type") == "ev":
            return consumer
        sched = consumer.get("charging_schedule")
        if sched and sched.get("enabled"):
            return consumer
    return None
