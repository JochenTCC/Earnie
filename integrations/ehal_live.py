"""Thin Live façade: OpenEMS/HA/Loxone EHAL adapters for plant I/O.

Implementation is split across sibling modules (behavior unchanged); their public
names stay importable from here: ``ehal_live_adapters`` (cached adapter factories),
``ehal_live_records`` (write-error file + write trace rows), ``ehal_live_soc``
(per-ESS SoC reads), ``ehal_live_inv`` (inverter AC limit writes), ``ehal_live_pv``
(PV attribution / house-load derive), ``ehal_live_ess_write`` (ESS C1 setpoint
writes), ``ehal_live_startup`` (safe startup push), ``ehal_live_evcs`` (EV charger
and HA flex-enable writes). Split modules
resolve shared names through ``ehal_live_ref.live`` so patches on this module hold.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import config
from ehal import EHAL_SCHEMA_VERSION, EhalWriteError  # noqa: F401
from integrations import loxone_client  # noqa: F401 — read via ``live.loxone_client``
from integrations.ehal_live_adapters import (  # noqa: F401 — façade re-exports
    ev_charger_markers,
    ev_charger_openems_channels,
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
    fetch_heat_feedback,
    fetch_heat_storage_temps,
    fetch_live_power,
    fetch_network_flex_live_kw,
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
from integrations.ehal_live_ess_write import (  # noqa: F401 — façade re-exports
    _OMIT_EXPORT_CAP,
    _build_ess_setpoint_docs,
    _control_ess_setpoints,
    write_ess_setpoints_from_control,
)
from integrations.ehal_live_evcs import (  # noqa: F401 — façade re-exports
    _evcs_mode_for_cycle,
    _write_one_charger,
    live_charger_consumers,
    live_ev_consumers,
    write_evcs_max_current_from_consumers,
    write_flex_enables_for_ha,
)
from integrations.ehal_live_pv import (  # noqa: F401 — façade re-exports
    _openems_production_ac_w,
    _plant_from_house_profiles,
    collect_scoped_pv_live_w,
    derive_sens_power_consumers_w,
    plant_pv_ac_w_live,
    prepare_live_telemetry,
    with_derived_sens_power_consumers,
    with_live_pv_attribution,
)
from integrations.ehal_live_startup import (  # noqa: F401 — façade re-exports
    _STARTUP_LIVE_POWER_KINDS,
    StartupEssLimitsMissing,
    _missing_live_power_limits,
    _push_safe_setpoints_loxone,
    _push_safe_setpoints_network,
    _startup_ess_limit_telemetry,
    push_safe_setpoints_on_startup,
)
from integrations.ha_adapter import HaAdapter, HaHttpError  # noqa: F401 — HaAdapter re-export
from integrations.loxone_adapter import LoxoneAdapter, LoxoneAdapterError  # noqa: F401
from integrations.loxone_client import LOXONE_EPOCH_TO_UNIX  # noqa: F401
from integrations.loxone_live_power import LiveFlexPowerResult  # noqa: F401
from integrations.openems_adapter import OpenemsAdapter, OpenemsHttpError  # noqa: F401
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere  # noqa: F401 — via ``live``

logger = logging.getLogger(__name__)


_soc_missing_warned: set[str] = set()


class _EhalNetworkAdapter(Protocol):
    def read_telemetry(self) -> dict[str, Any]: ...

    def write_setpoints(self, setpoint: dict[str, Any]) -> EhalWriteError | None: ...

    def write_evcs_setpoints(
        self,
        charger_id: str,
        setpoint: dict[str, Any],
        *,
        voltage_v: float,
        phases: int,
    ) -> EhalWriteError | None: ...

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


LIVE_POWER_READ_ERRORS: tuple[type[BaseException], ...] = (
    OpenemsHttpError,
    HaHttpError,
    LoxoneAdapterError,
    ValueError,
    OSError,
)


def read_live_power_kw() -> dict[str, float] | None:
    """Return Live power dict (kW): grid ``+`` = import, battery ``+`` = discharge.

    ``None`` when the EHAL read fails (logged); ``read_live_power_kw_strict`` raises.
    """
    try:
        return read_live_power_kw_strict()
    except LIVE_POWER_READ_ERRORS as exc:
        logger.error("EHAL live power read failed: %s", exc)
        return None


def read_live_power_kw_strict() -> dict[str, float]:
    """Live power dict (kW) from the EHAL adapter; raises ``LIVE_POWER_READ_ERRORS``."""
    telemetry = prepare_live_telemetry(get_adapter().read_telemetry())

    pv =max(0.0, plant_pv_ac_w_live(telemetry) / 1000.0)
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
