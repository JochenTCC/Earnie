"""Thin Live façade: OpenEMS/HA/Loxone EHAL adapters for plant I/O."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Protocol

import config
from ehal import EHAL_SCHEMA_VERSION, EhalWriteError, validate_write_error
from ehal.models import canonicalize_ha_entity_keys
from integrations import loxone_client
from integrations.ha_adapter import HaAdapter, HaConfig, HaHttpError
from integrations.loxone_adapter import LoxoneAdapter, LoxoneAdapterError, LoxoneConfig
from integrations.openems_adapter import OpenemsAdapter, OpenemsConfig, OpenemsHttpError
from runtime_store.persist_paths import runtime_path
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere

logger = logging.getLogger(__name__)

WRITE_ERROR_FILENAME = "ehal_write_error.json"

_openems_adapter: OpenemsAdapter | None = None
_ha_adapter: HaAdapter | None = None
_loxone_adapter: LoxoneAdapter | None = None


class _EhalNetworkAdapter(Protocol):
    def read_telemetry(self) -> dict[str, Any]: ...

    def write_setpoints(self, setpoint: dict[str, Any], **kwargs: Any) -> EhalWriteError | None: ...

    def capabilities(self) -> dict[str, Any]: ...

    @property
    def cfg(self) -> Any: ...


def is_openems_backend() -> bool:
    return str(config.get("EHAL_BACKEND") or "").strip().lower() == "openems"


def is_ha_backend() -> bool:
    return str(config.get("EHAL_BACKEND") or "").strip().lower() == "ha"


def is_loxone_backend() -> bool:
    backend = str(config.get("EHAL_BACKEND") or "").strip().lower()
    return backend in ("", "loxone")


def is_ehal_network_backend() -> bool:
    """True for OpenEMS/HA only (skips Loxone flex / Huawei extras write path)."""
    return is_openems_backend() or is_ha_backend()


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


def derive_sens_power_consumers_w(telemetry: dict[str, Any]) -> float:
    """House load W: mapped value if present, else max(0, PV − grid − ESS)."""
    mapped = telemetry.get("sens_power_consumers")
    if mapped is not None:
        return max(0.0, float(mapped))
    pv = float(telemetry["sens_pv_production_active"])
    grid = float(telemetry["sens_grid_power_active"])
    ess = float(telemetry.get("sens_ess_power") or 0.0)
    return max(0.0, pv - grid - ess)


def with_derived_sens_power_consumers(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with sens_power_consumers filled when missing/null."""
    out = dict(telemetry)
    if out.get("sens_power_consumers") is None:
        out["sens_power_consumers"] = derive_sens_power_consumers_w(out)
    return out


def get_openems_adapter() -> OpenemsAdapter:
    global _openems_adapter
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
    if _openems_adapter is not None and _openems_adapter.cfg != cfg:
        _openems_adapter = None
    if _openems_adapter is None:
        _openems_adapter = OpenemsAdapter(cfg)
    return _openems_adapter


def get_ha_adapter() -> HaAdapter:
    global _ha_adapter
    base_url = str(config.get("EHAL_HA_BASE_URL") or "").strip()
    token = str(config.get("EHAL_HA_TOKEN") or "").strip()
    if not base_url:
        raise ValueError(
            "ehal.backend=ha requires ehal.ha.base_url (EHAL_HA_BASE_URL)."
        )
    if not token:
        raise ValueError(
            "ehal.backend=ha requires ehal.ha.token (EHAL_HA_TOKEN)."
        )
    entities = config.get("EHAL_HA_ENTITIES") or {}
    if not isinstance(entities, dict):
        entities = {}
    sign = config.get("EHAL_HA_SIGN") or {}
    if not isinstance(sign, dict):
        sign = {}
    cfg = HaConfig(
        base_url=base_url,
        token=token,
        adapter_id=str(config.get("EHAL_ADAPTER_ID") or "ha-home"),
        entities=canonicalize_ha_entity_keys(
            {str(k): str(v) for k, v in entities.items()}
        ),
        sign=canonicalize_ha_entity_keys({str(k): str(v) for k, v in sign.items()}),
        timeout_sec=float(config.get("GLOBAL_TIMEOUT") or 10),
    )
    if _ha_adapter is not None and _ha_adapter.cfg != cfg:
        _ha_adapter = None
    if _ha_adapter is None:
        _ha_adapter = HaAdapter(cfg)
    return _ha_adapter


def get_loxone_adapter() -> LoxoneAdapter:
    global _loxone_adapter
    ev = _first_ev_loxone_bindings()
    cfg = LoxoneConfig(
        adapter_id=str(config.get("EHAL_ADAPTER_ID") or "loxone-home"),
        soc_name=str(config.get("LOXONE_SOC_NAME") or ""),
        pv_power_name=str(config.get("LOXONE_PV_POWER_NAME") or ""),
        battery_power_name=str(config.get("LOXONE_BATTERY_POWER_NAME") or ""),
        grid_power_name=str(config.get("LOXONE_GRID_POWER_NAME") or ""),
        charge_power_name=str(config.get("LOXONE_TARGET_CHARGE_POWER_NAME") or ""),
        discharge_power_name=str(
            config.get("LOXONE_TARGET_DISCHARGE_POWER_NAME") or ""
        ),
        active_power_name=str(config.get("LOXONE_TARGET_ACTIVE_POWER_NAME") or ""),
        control_cmd_name=str(config.get("LOXONE_CONTROL_CMD_NAME") or ""),
        consumers_power_name=str(config.get("LOXONE_CONSUMERS_POWER_NAME") or ""),
        evcs_max_current_name=str(ev.get("evcs_max_current_name") or ""),
        pv_follow_name=str(ev.get("pv_follow_name") or ""),
        charge_immediate_name=str(ev.get("charge_immediate_name") or ""),
        timeout_sec=float(config.get("GLOBAL_TIMEOUT") or 10),
    )
    if _loxone_adapter is not None and _loxone_adapter.cfg != cfg:
        _loxone_adapter = None
    if _loxone_adapter is None:
        _loxone_adapter = LoxoneAdapter(cfg)
    return _loxone_adapter


def get_network_adapter() -> _EhalNetworkAdapter:
    """OpenEMS or HA adapter (raises if Loxone backend)."""
    if is_ha_backend():
        return get_ha_adapter()
    if is_openems_backend():
        return get_openems_adapter()
    raise ValueError("get_network_adapter requires ehal.backend openems or ha")


def get_adapter() -> _EhalNetworkAdapter:
    """Active EHAL adapter including Loxone (default production path)."""
    if is_ha_backend():
        return get_ha_adapter()
    if is_openems_backend():
        return get_openems_adapter()
    return get_loxone_adapter()


def reset_adapter_cache() -> None:
    """Test helper: drop cached adapter instances."""
    global _openems_adapter, _ha_adapter, _loxone_adapter
    _openems_adapter = None
    _ha_adapter = None
    _loxone_adapter = None


def read_ess_soc() -> float | None:
    try:
        telemetry = with_derived_sens_power_consumers(get_adapter().read_telemetry())
    except (
        OpenemsHttpError,
        HaHttpError,
        LoxoneAdapterError,
        ValueError,
        OSError,
    ) as exc:
        logger.error("EHAL SoC read failed: %s", exc)
        return None
    return float(telemetry["sens_ess_soc"])


def read_live_power_kw() -> dict[str, float] | None:
    """Return Live power dict (kW) in Loxone-compatible signs (+ battery = charge)."""
    try:
        telemetry = with_derived_sens_power_consumers(get_adapter().read_telemetry())
    except (
        OpenemsHttpError,
        HaHttpError,
        LoxoneAdapterError,
        ValueError,
        OSError,
    ) as exc:
        logger.error("EHAL live power read failed: %s", exc)
        return None

    pv = max(0.0, float(telemetry["sens_pv_production_active"]) / 1000.0)
    grid = float(telemetry["sens_grid_power_active"]) / 1000.0
    ess_w = telemetry.get("sens_ess_power")
    if ess_w is None:
        battery = 0.0
    else:
        # EHAL sens_ess_power: +discharge; Live/Loxone convention: +charge
        battery = -float(ess_w) / 1000.0
    house = pv + battery + grid
    return {
        "pv": round(pv, 2),
        "house": round(house, 2),
        "battery": round(battery, 2),
        "grid": round(grid, 2),
    }


def write_ess_setpoints_from_control(
    mode: int, target_power_kw: float, max_power_kw: float | None = None
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Map optimizer mode/power to EHAL Design C1 ESS setpoints."""
    if max_power_kw is None:
        max_power_kw = float(config.get_battery_params().get("max_power_kw") or 0.0)
    active_kw, charge_kw, discharge_kw, control_cmd = loxone_client.map_ess_setpoints(
        mode, target_power_kw, float(max_power_kw)
    )
    adapter = get_network_adapter()
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    charge_w = max(0.0, float(charge_kw) * 1000.0)
    discharge_w = max(0.0, float(discharge_kw) * 1000.0)
    setpoint: dict[str, Any] = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter.cfg.adapter_id,
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
    error = adapter.write_setpoints(setpoint)
    if error is not None:
        persist_write_error(error)
    records = build_ehal_write_records(
        record_fields,
        written_at=ts,
        error=error,
    )
    return error, records


def write_ess_limits_from_huawei(
    mode: int, target_power_kw: float
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Deprecated alias for :func:`write_ess_setpoints_from_control`."""
    return write_ess_setpoints_from_control(mode, target_power_kw)


def clamp_ess_test_target_kw(
    target_power_kw: float, max_power_kw: float | None = None
) -> float:
    """Non-negative target kW, capped by battery max when max > 0."""
    if max_power_kw is None:
        max_power_kw = float(config.get_battery_params().get("max_power_kw") or 0.0)
    max_kw = max(0.0, float(max_power_kw))
    target = abs(float(target_power_kw))
    if max_kw > 0.0:
        return min(target, max_kw)
    return target


def push_safe_setpoints_on_startup() -> None:
    """Force-write safe ESS/flex setpoints once at daemon start (before first optimize).

    Does not update ``optimizer_run_state`` / ``loxone_sent``. Soft-fail: log only.
    Skip via ``EARNIE_SKIP_SAFE_SETPOINTS_ON_START=1`` or silent mode.
    """
    from runtime_store.env_vars import is_truthy

    if is_truthy("SKIP_SAFE_SETPOINTS_ON_START"):
        logger.info(
            "Safe setpoint startup push skipped (EARNIE_SKIP_SAFE_SETPOINTS_ON_START)."
        )
        return
    if config.is_loxone_silent_mode():
        logger.info("Silent-Modus: Safe setpoint startup push übersprungen.")
        return
    if is_ehal_network_backend():
        _push_safe_setpoints_network()
    else:
        _push_safe_setpoints_loxone()


def _push_safe_setpoints_network() -> None:
    backend = "HA" if is_ha_backend() else "OpenEMS"
    logger.info(
        "Startup: sende sichere EHAL-Sollwerte (ESS Automatik, EVCS 0 A) an %s...",
        backend,
    )
    err_ess, _ess_records = write_ess_setpoints_from_control(0, 0.0)
    err_evcs, _evcs_records = write_evcs_max_current_from_consumers({})
    if err_ess is None and err_evcs is None:
        clear_write_error()
        logger.info("Startup: sichere EHAL-Sollwerte an %s gesendet.", backend)
        return
    parts: list[str] = []
    if err_ess is not None:
        parts.append(str(err_ess.get("message") or "ESS"))
    if err_evcs is not None:
        parts.append(str(err_evcs.get("message") or "EVCS"))
    logger.error(
        "Startup: sichere EHAL-Sollwerte an %s teilweise fehlgeschlagen: %s",
        backend,
        "; ".join(parts),
    )


def _push_safe_setpoints_loxone() -> None:
    logger.info(
        "Startup: sende sichere Loxone-Sollwerte "
        "(ESS Automatik, Freigabe/Sollwerte aus)..."
    )
    huawei = loxone_client.send_huawei_modbus_states(0, 0.0, 0.0)
    flex = loxone_client.send_flexible_consumer_states({}, None, None)
    failed = [
        row
        for row in (huawei + flex)
        if not getattr(row, "success", True)
    ]
    if not failed:
        logger.info("Startup: sichere Loxone-Sollwerte gesendet.")
        return
    logger.error(
        "Startup: sichere Loxone-Sollwerte teilweise fehlgeschlagen (%s Feld(er)).",
        len(failed),
    )


def force_write_ess_test_setpoints(
    mode: int,
    target_power_kw: float,
    *,
    max_power_kw: float | None = None,
) -> tuple[str | None, list[dict[str, Any]], str]:
    """Manual ESS C1 test write — same southbound path as ``main.py``.

    Returns ``(error_message_or_None, write_records, backend_label)``.
    Caller must ensure the optimizer daemon is stopped before invoking.
    """
    if config.is_loxone_silent_mode():
        return "Silent-Modus aktiv — keine Steuerwerte.", [], "silent"
    if max_power_kw is None:
        max_power_kw = float(config.get_battery_params().get("max_power_kw") or 0.0)
    target = clamp_ess_test_target_kw(target_power_kw, max_power_kw)
    if is_ehal_network_backend():
        return _force_write_ess_network(mode, target, float(max_power_kw))
    return _force_write_ess_loxone(mode, target)


def _force_write_ess_network(
    mode: int, target_kw: float, max_power_kw: float
) -> tuple[str | None, list[dict[str, Any]], str]:
    backend = "HA" if is_ha_backend() else "OpenEMS"
    error, records = write_ess_setpoints_from_control(mode, target_kw, max_power_kw)
    if error is None:
        clear_write_error()
        return None, records, backend
    return str(error.get("message") or "EHAL Schreibfehler"), records, backend


def _force_write_ess_loxone(
    mode: int, target_kw: float
) -> tuple[str | None, list[dict[str, Any]], str]:
    from integrations.loxone_comm_trace import serialize_write_records

    raw = loxone_client.send_huawei_modbus_states(mode, target_kw, 0.0)
    records = serialize_write_records(raw)
    failed = [row for row in records if not row.get("success")]
    if failed:
        return f"Loxone-Schreibfehler ({len(failed)} Feld(er))", records, "Loxone"
    return None, records, "Loxone"


def write_evcs_max_current_from_consumers(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Write set_evcs_max_current from first EV consumer planned power (kW→A)."""
    consumer = _first_ev_consumer()
    if consumer is None:
        logger.info("EHAL: no EV consumer configured — skip EVCS write")
        return None, []

    cid = consumer["id"]
    planned_kw = max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0))
    ctx = (charging_contexts or {}).get(cid)
    if ctx is not None and not ctx.get("active", True):
        planned_kw = 0.0
    if ctx is not None and ctx.get("anticipated") and not ctx.get("plugged_in"):
        planned_kw = 0.0

    voltage_v, phases = ev_nominal_power_conversion(consumer)
    amps = kw_to_ampere(planned_kw, voltage_v=voltage_v, phases=phases)
    adapter = get_network_adapter()
    if not adapter.capabilities()["supports_evcs_current"]:
        logger.info("EHAL: supports_evcs_current=false — skip EVCS write")
        return None, []

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    amps_out = max(0.0, amps)
    setpoint = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter.cfg.adapter_id,
        "set_evcs_max_current": amps_out,
    }
    error = adapter.write_setpoints(
        setpoint, evcs_voltage_v=voltage_v, evcs_phases=phases
    )
    if error is not None:
        persist_write_error(error)
    records = build_ehal_write_records(
        {"set_evcs_max_current": amps_out},
        written_at=ts,
        error=error,
    )
    return error, records


def build_ehal_write_records(
    fields: dict[str, float],
    *,
    written_at: str,
    error: EhalWriteError | None,
) -> list[dict[str, Any]]:
    """Compact write trace rows for optimizer_run_state.ehal_writes."""
    failed = set(error.get("failed_fields") or []) if error else set()
    message = str(error.get("message") or "") if error else ""
    rows: list[dict[str, Any]] = []
    for field, value in fields.items():
        if error is None:
            ok = True
        elif failed:
            ok = field not in failed
        else:
            ok = False
        rows.append(
            {
                "field": field,
                "value": value,
                "success": ok,
                "written_at": written_at,
                "message": "" if ok else message,
            }
        )
    return rows


def _first_ev_consumer() -> dict | None:
    for consumer in config.get_flexible_consumers():
        if consumer.get("type") == "ev":
            return consumer
        sched = consumer.get("charging_schedule")
        if sched and sched.get("enabled"):
            return consumer
    return None


def _first_ev_loxone_bindings() -> dict[str, str]:
    """EV write markers from first EV consumer ``ehal_bindings`` (+ legacy dual-read)."""
    from settings.ehal_marker_resolve import (
        marker_charge_immediate,
        marker_pv_follow,
        marker_set_evcs_max_current,
    )

    consumer = _first_ev_consumer()
    if consumer is None:
        return {}
    return {
        "evcs_max_current_name": marker_set_evcs_max_current(consumer),
        "pv_follow_name": marker_pv_follow(consumer),
        "charge_immediate_name": marker_charge_immediate(consumer),
    }
