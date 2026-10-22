"""Thin Live façade: OpenEMS/HA/Loxone EHAL adapters for plant I/O.

Implementation is split across sibling modules (behavior unchanged); their public
names stay importable from here: ``ehal_live_adapters`` (cached adapter factories),
``ehal_live_records`` (write-error file + write trace rows), ``ehal_live_soc``
(per-ESS SoC reads), ``ehal_live_inv`` (inverter AC limit writes). Split modules
resolve shared names through ``ehal_live_ref.live`` so patches on this module hold.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

import config
from ehal import EHAL_SCHEMA_VERSION, EhalWriteError
from integrations import loxone_client  # noqa: F401 — read via ``live.loxone_client``
from integrations.ehal_live_adapters import (  # noqa: F401 — façade re-exports
    _first_ev_loxone_bindings,
    _standby_source_select_merker,
    get_ha_adapter,
    get_loxone_adapter,
    get_openems_adapter,
    reset_adapter_cache,
)
from integrations.ehal_live_inv import write_inv_ac_limits_from_plan
from integrations.ehal_live_records import (  # noqa: F401 — façade re-exports
    SKIPPED_MESSAGE,
    WRITE_ERROR_FILENAME,
    _last_skipped,
    _last_unconfigured,
    build_ehal_write_records,
    clear_write_error,
    load_write_error,
    persist_write_error,
    write_error_path,
)
from integrations.ehal_live_soc import (  # noqa: F401 — façade re-exports
    _mappable_batteries_for_soc,
    _read_soc_from_address,
    _soc_address_for_battery,
    _warn_soc_missing_once,
    filter_planning_batteries_with_soc,
    read_ess_soc,
    read_ess_soc_by_id,
)
from integrations.ehal_live_ess_limits import (  # noqa: F401 — façade re-exports
    enrich_telemetry_with_ess_live_limits,
)
from integrations.ehal_live_ops import (  # noqa: F401 — façade re-exports
    OMIT_EXPORT_CAP,
    build_sent_loxone_snapshot,
    consumers_with_live_nominal_power,
    fetch_filter_native_start_hour,
    fetch_flexible_consumers_live_kw,
    fetch_heat_storage_temps,
    fetch_live_power,
    fetch_ready_by_time,
    fetch_thermal_readings,
    format_ready_by_display,
    house_profile_power_consumers,
    load_default_house_doc,
    map_ess_setpoints,
    publish_setpoint_traced,
    read_absent_mode,
    read_consumer_meter_kw,
    read_generic_value,
    read_optional_temp_c,
    resolve_consumer_battery_capacity_kwh,
    resolve_consumer_live_power_kw,
    resolve_consumer_nominal_power_kw,
    resolve_flexible_consumers_live_power,
    write_flexible_consumer_enables,
    write_flexible_consumer_states,
    write_huawei_modbus_states,
)
from integrations.ha_adapter import HaAdapter, HaHttpError  # noqa: F401 — HaAdapter re-export
from integrations.loxone_adapter import LoxoneAdapter, LoxoneAdapterError  # noqa: F401
from integrations.loxone_client import LOXONE_EPOCH_TO_UNIX  # noqa: F401
from integrations.loxone_live_power import LiveFlexPowerResult  # noqa: F401
from integrations.openems_adapter import OpenemsAdapter, OpenemsHttpError  # noqa: F401
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere

logger = logging.getLogger(__name__)


_soc_missing_warned: set[str] = set()


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


def is_ha_push_transport() -> bool:
    """HA is push-only (Binding P5e); True whenever the HA backend is active."""
    return is_ha_backend()


def is_loxone_backend() -> bool:
    backend = str(config.get("EHAL_BACKEND") or "").strip().lower()
    return backend in ("", "loxone")


def is_ehal_network_backend() -> bool:
    """True for OpenEMS/HA only (skips Loxone flex / Huawei extras write path)."""
    return is_openems_backend() or is_ha_backend()










def _plant_from_house_profiles() -> dict:
    try:
        from integrations.pv_attribution import load_house_for_attribution

        house = load_house_for_attribution()
        plant = house.get("plant") if isinstance(house, dict) else None
        return plant if isinstance(plant, dict) else {}
    except Exception:  # noqa: BLE001 — derive must stay usable in tests
        return {}


def derive_sens_power_consumers_w(
    telemetry: dict[str, Any],
    *,
    plant_pv_w: float,
    plant: dict | None = None,
) -> float:
    """House load W: mapped value if present, else PV + grid + ESS with P2 tolerance."""
    from integrations.plant_balance import (
        balance_tolerances_from_plant,
        derive_sens_power_consumers_w as derive_balanced,
    )

    plant_map = plant if isinstance(plant, dict) else _plant_from_house_profiles()
    pct, watts = balance_tolerances_from_plant(plant_map)
    return derive_balanced(
        telemetry,
        plant_pv_w=plant_pv_w,
        tolerance_pct=pct,
        tolerance_w=watts,
    )


def with_derived_sens_power_consumers(
    telemetry: dict[str, Any],
    *,
    plant_pv_w: float,
    plant: dict | None = None,
) -> dict[str, Any]:
    """Return a copy with sens_power_consumers filled when missing/null."""
    out = dict(telemetry)
    if out.get("sens_power_consumers") is None:
        out["sens_power_consumers"] = derive_sens_power_consumers_w(
            out, plant_pv_w=plant_pv_w, plant=plant
        )
    return out


def collect_scoped_pv_live_w() -> dict[str, float]:
    """Mapped ``inv.*.sens_inv_power_pv`` / ``pv.*.sens_pv_production_active`` live W."""
    from integrations.pv_attribution import (
        collect_scoped_pv_live_from_bindings,
        load_components_for_attribution,
        read_scoped_pv_ha,
        read_scoped_pv_loxone,
    )

    components = load_components_for_attribution()
    backend = str(config.get("EHAL_BACKEND") or "loxone").strip().lower()
    if backend == "ha":
        return collect_scoped_pv_live_from_bindings(
            components, read_value=read_scoped_pv_ha
        )
    if backend == "loxone":
        return collect_scoped_pv_live_from_bindings(
            components, read_value=read_scoped_pv_loxone
        )
    return {}


def with_live_pv_attribution(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Fill missing ``inv.*.sens_inv_power_pv`` from complete per-PV maps.

    Does not write bare plant ``sens_pv_production_active`` (retired from telemetry).
    """
    from integrations.pv_attribution import (
        load_components_for_attribution,
        with_attributed_plant_pv,
    )

    components = load_components_for_attribution()
    inverters = list(components.get("inverters") or [])
    pv_systems = list(components.get("pv_systems") or [])
    scoped = collect_scoped_pv_live_w()
    # Prefer values already on telemetry (tests / adapters) over fresh reads.
    for key, value in telemetry.items():
        key_s = str(key)
        if (
            key_s.startswith("inv.") and key_s.endswith(".sens_inv_power_pv")
        ) or (
            key_s.startswith("pv.") and key_s.endswith(".sens_pv_production_active")
        ):
            if value is not None:
                scoped[key_s] = max(0.0, float(value))
    return with_attributed_plant_pv(
        telemetry,
        scoped_live=scoped,
        inverters=inverters,
        pv_systems=pv_systems,
    )


def plant_pv_ac_w_live(telemetry: dict[str, Any]) -> float:
    """Plant AC PV W from scoped inv/pv on ``telemetry`` (OpenEMS: _sum channel)."""
    from integrations.pv_attribution import (
        derive_plant_pv_ac_w,
        grid_tied_inverters_with_pv,
        load_components_for_attribution,
        plant_pv_derive_coverage_complete,
        scoped_pv_live_from_telemetry,
    )

    components = load_components_for_attribution()
    inverters = list(components.get("inverters") or [])
    pv_systems = list(components.get("pv_systems") or [])
    scoped = scoped_pv_live_from_telemetry(telemetry)
    scoped.update(collect_scoped_pv_live_w())
    eligible = grid_tied_inverters_with_pv(inverters, pv_systems)
    if not eligible:
        return 0.0
    if plant_pv_derive_coverage_complete(
        inverters, pv_systems, scoped_live=scoped
    ):
        return derive_plant_pv_ac_w(scoped, inverters, pv_systems)
    backend = str(config.get("EHAL_BACKEND") or "loxone").strip().lower()
    if backend == "openems":
        return _openems_production_ac_w()
    return derive_plant_pv_ac_w(scoped, inverters, pv_systems)


def _openems_production_ac_w() -> float:
    """OpenEMS ``_sum/ProductionActivePower`` as plant AC PV (already AC)."""
    adapter = get_openems_adapter()
    raw = adapter.read_channel("_sum", "ProductionActivePower")
    if raw is None:
        raise ValueError(
            "OpenEMS ProductionActivePower missing; map inv.*.sens_inv_power_pv "
            "or ensure _sum/ProductionActivePower is available."
        )
    return max(0.0, float(raw))


def prepare_live_telemetry(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Post-read: inv/pv attribution then house-load derive from plant AC PV."""
    attributed = with_live_pv_attribution(telemetry)
    plant_pv = plant_pv_ac_w_live(attributed)
    return with_derived_sens_power_consumers(attributed, plant_pv_w=plant_pv)










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


















def read_live_power_kw() -> dict[str, float] | None:
    """Return Live power dict (kW): grid ``+`` = import, battery ``+`` = discharge."""
    try:
        telemetry = prepare_live_telemetry(get_adapter().read_telemetry())
    except (
        OpenemsHttpError,
        HaHttpError,
        LoxoneAdapterError,
        ValueError,
        OSError,
    ) as exc:
        logger.error("EHAL live power read failed: %s", exc)
        return None

    pv = max(0.0, plant_pv_ac_w_live(telemetry) / 1000.0)
    grid = float(telemetry["sens_grid_power_active"]) / 1000.0
    ess_w = telemetry.get("sens_ess_power")
    if ess_w is None:
        battery = 0.0
    else:
        # EHAL sens_ess_power and Live dict share the sign: + = discharge
        battery = float(ess_w) / 1000.0
    house = pv + battery + grid
    return {
        "pv": round(pv, 2),
        "house": round(house, 2),
        "battery": round(battery, 2),
        "grid": round(grid, 2),
    }


_OMIT_EXPORT_CAP = object()


def _control_ess_setpoints(
    control: str,
    mode: int,
    target_power_kw: float,
    max_charge_kw: float,
    max_discharge_kw: float,
) -> tuple[float | None, float, float, int]:
    """``map_ess_setpoints`` honouring limits-only battery control (no active power)."""
    from house_config.battery_control import BATTERY_CONTROL_LIMITS_ONLY

    active_kw, charge_kw, discharge_kw, control_cmd = map_ess_setpoints(
        mode, target_power_kw, max_charge_kw, max_discharge_kw
    )
    if control == BATTERY_CONTROL_LIMITS_ONLY:
        active_kw = None
        if mode in (1, 3):
            active_kw, charge_kw, discharge_kw, control_cmd = map_ess_setpoints(
                0, 0.0, max_charge_kw, max_discharge_kw
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


def write_ess_setpoints_from_control(
    mode: int,
    target_power_kw: float,
    max_power_kw: float | None = None,
    *,
    max_charge_power_kw: float | None = None,
    max_discharge_power_kw: float | None = None,
    export_cap_kw: float | None | object = _OMIT_EXPORT_CAP,
    telemetry: dict[str, Any] | None = None,
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Map optimizer mode/power to EHAL Design C1 ESS setpoints.

    When ``export_cap_kw`` is passed (including ``None`` = unconstrained), also write
    ``set_grid_export_power_limit`` (W magnitude; plant export maximum = PV kWp + force
    discharge kW when unconstrained, see ``live_unconstrained_export_kw``).
    """
    from house_config.battery_control import (
        BATTERY_CONTROL_READ_ONLY,
        control_from_battery_params,
    )
    from settings.ess_limits_resolve import apply_effective_ess_limits

    battery_params = apply_effective_ess_limits(
        config.get_battery_params(), telemetry=telemetry
    )
    control = control_from_battery_params(battery_params)
    if control == BATTERY_CONTROL_READ_ONLY:
        return None, []

    if max_charge_power_kw is None and max_discharge_power_kw is None and max_power_kw is not None:
        max_charge_power_kw = float(max_power_kw)
        max_discharge_power_kw = float(max_power_kw)
    if max_charge_power_kw is None:
        max_charge_power_kw = float(battery_params.get("max_charge_power_kw") or 0.0)
    if max_discharge_power_kw is None:
        max_discharge_power_kw = float(
            battery_params.get("max_discharge_power_kw") or 0.0
        )
    active_kw, charge_kw, discharge_kw, control_cmd = _control_ess_setpoints(
        control,
        mode,
        target_power_kw,
        float(max_charge_power_kw),
        float(max_discharge_power_kw),
    )
    adapter = get_network_adapter()
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    setpoint, record_fields = _build_ess_setpoint_docs(
        adapter.cfg.adapter_id,
        ts,
        (active_kw, charge_kw, discharge_kw, control_cmd),
        export_cap_kw,
    )
    error = adapter.write_setpoints(setpoint)
    if error is not None:
        persist_write_error(error)
    records = build_ehal_write_records(
        record_fields,
        written_at=ts,
        error=error,
        skipped=_last_skipped(adapter),
        unconfigured=_last_unconfigured(adapter),
    )
    return error, records






def _openems_channel_parts(binding: str) -> tuple[str, str] | None:
    text = str(binding or "").strip()
    if "/" not in text:
        return None
    component, channel = text.split("/", 1)
    component = component.strip()
    channel = channel.strip()
    if not component or not channel:
        return None
    return component, channel










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
    try:
        if is_ehal_network_backend():
            _push_safe_setpoints_network()
        else:
            _push_safe_setpoints_loxone()
    except Exception:
        # main.py does not log fatal startup errors; without this the daemon dies
        # with the traceback only on stderr and ``earnie.log`` just stops.
        logger.exception("Startup: sichere Sollwerte fehlgeschlagen — main.py bricht ab.")
        raise


def _push_safe_setpoints_network() -> None:
    backend = "HA" if is_ha_backend() else "OpenEMS"
    logger.info(
        "Startup: sende sichere EHAL-Sollwerte (ESS Automatik, EVCS 0 A) an %s...",
        backend,
    )
    err_ess, _ess_records = write_ess_setpoints_from_control(0, 0.0)
    err_evcs, _evcs_records = write_evcs_max_current_from_consumers({})
    err_inv, _inv_records = write_inv_ac_limits_from_plan(plant_curtail_kw=0.0)
    if err_ess is None and err_evcs is None and err_inv is None:
        clear_write_error()
        logger.info("Startup: sichere EHAL-Sollwerte an %s gesendet.", backend)
        return
    parts: list[str] = []
    if err_ess is not None:
        parts.append(str(err_ess.get("message") or "ESS"))
    if err_evcs is not None:
        parts.append(str(err_evcs.get("message") or "EVCS"))
    if err_inv is not None:
        parts.append(str(err_inv.get("message") or "INV"))
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
    huawei = write_huawei_modbus_states(0, 0.0, 0.0)
    flex = write_flexible_consumer_states({}, None, None)
    _inv_err, inv_rows = write_inv_ac_limits_from_plan(plant_curtail_kw=0.0)
    failed = [
        row
        for row in (huawei + flex)
        if not getattr(row, "success", True)
    ]
    failed_inv = [row for row in inv_rows if not row.get("success")]
    if not failed and not failed_inv:
        logger.info("Startup: sichere Loxone-Sollwerte gesendet.")
        return
    logger.error(
        "Startup: sichere Loxone-Sollwerte teilweise fehlgeschlagen (%s Feld(er)).",
        len(failed) + len(failed_inv),
    )


def write_flex_enables_for_ha(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Publish the flex ``set_enable`` (heat pump, pool, generic) for the HA backend.

    Returns ``optimizer_run_state.ehal_writes`` rows. The EV current is not part of this
    (``write_evcs_max_current_from_consumers`` writes it).
    """
    records = write_flexible_consumer_enables(
        consumer_powers, charging_contexts, consumer_pv_follow
    )
    return [
        {
            "field": record.io_name,
            "value": record.value,
            "success": record.success,
            "written_at": record.written_at,
            "message": "" if record.success else "EHAL publish rejected",
        }
        for record in records
    ]


def write_evcs_max_current_from_consumers(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Write set_evcs_max_current from first EV consumer planned power (kW→A).

    HA backend: also ``set_evcs_mode`` (skipped by the adapter when not activated). With
    "Sofort laden" only the mode ``now`` goes out and no current, as on the Loxone path.
    """
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
    written: dict[str, Any] = {}
    immediate = is_ha_backend() and bool((ctx or {}).get("skip_loxone_output"))
    if not immediate:
        written["set_evcs_max_current"] = amps_out
    if is_ha_backend():
        written["set_evcs_mode"] = _evcs_mode_for_cycle(
            consumer, planned_kw, amps_out, immediate, consumer_pv_follow
        )
    setpoint = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter.cfg.adapter_id,
        **written,
    }
    error = adapter.write_setpoints(
        setpoint, evcs_voltage_v=voltage_v, evcs_phases=phases
    )
    if error is not None:
        persist_write_error(error)
    records = build_ehal_write_records(
        written,
        written_at=ts,
        error=error,
        skipped=_last_skipped(adapter),
        unconfigured=_last_unconfigured(adapter),
    )
    return error, records


def _evcs_mode_for_cycle(
    consumer: dict,
    planned_kw: float,
    amps: float,
    immediate: bool,
    consumer_pv_follow: dict[str, int] | None,
) -> str:
    from optimizer.consumer_power import loxone_control_outputs, set_evcs_mode_for_plan

    plan_pv = int((consumer_pv_follow or {}).get(consumer["id"], 0) or 0)
    _, pv_out = loxone_control_outputs(consumer, planned_kw, plan_pv)
    return set_evcs_mode_for_plan(
        pv_follow=int(pv_out), immediate=immediate, charging=amps > 1e-6
    )


def _first_ev_consumer() -> dict | None:
    for consumer in config.get_flexible_consumers():
        if consumer.get("type") == "ev":
            return consumer
        sched = consumer.get("charging_schedule")
        if sched and sched.get("enabled"):
            return consumer
    return None


