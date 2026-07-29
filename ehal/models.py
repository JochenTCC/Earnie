"""TypedDict models mirroring share/ehal/*.schema.json (schema_version 2)."""

from __future__ import annotations

from typing import NotRequired, TypedDict

EHAL_SCHEMA_VERSION = 2

# Legacy M1 unprefixed / renamed → §C aliases (HA entity map / dual-read during 2.4.j).
TELEMETRY_FIELD_ALIASES: dict[str, str] = {
    "grid_power_active": "sens_grid_power_active",
    "pv_production_active": "sens_pv_production_active",
    "ess_soc": "sens_ess_soc",
    "ess_power": "sens_ess_power",
    "evcs_active_power": "sens_evcs_active_power",
    "set_evcs_current": "set_evcs_max_current",
    "sens_evcs_nominal_current": "get_evcs_nominal_current",
}


class EhalEnvelope(TypedDict):
    schema_version: int
    ts: str
    adapter_id: str


class EhalTelemetry(TypedDict):
    schema_version: int
    ts: str
    adapter_id: str
    sens_grid_power_active: float
    sens_pv_production_active: float
    sens_ess_soc: float
    sens_ess_power: NotRequired[float | None]
    sens_evcs_active_power: NotRequired[float | None]
    sens_power_consumers: NotRequired[float | None]
    sens_evcs_connected: NotRequired[bool | None]
    sens_evcs_soc_act: NotRequired[float | None]
    get_evcs_nominal_current: NotRequired[float | None]
    sens_evcs_bat_capacity: NotRequired[float | None]
    get_evcs_ready_by_time: NotRequired[str | None]
    get_evcs_limit_soc: NotRequired[float | None]


class EhalSetpoint(TypedDict):
    schema_version: int
    ts: str
    adapter_id: str
    set_ess_charge_power_limit: NotRequired[float]
    set_ess_discharge_power_limit: NotRequired[float]
    set_ess_mode: NotRequired[str | float]
    set_evcs_max_current: NotRequired[float]
    set_evcs_mode: NotRequired[str]


class EhalCapabilities(TypedDict):
    schema_version: int
    ts: str
    adapter_id: str
    supports_ess_write: bool
    supports_evcs_current: bool


class EhalWriteError(TypedDict):
    schema_version: int
    ts: str
    adapter_id: str
    failed_fields: list[str]
    message: str
    retryable: bool
    hub_status: NotRequired[str | None]


def canonicalize_ha_entity_keys(entities: dict[str, str]) -> dict[str, str]:
    """Map legacy unprefixed HA entity keys to §C names; prefer explicit §C keys."""
    out: dict[str, str] = {}
    for key, value in entities.items():
        canonical = TELEMETRY_FIELD_ALIASES.get(key, key)
        name = str(value or "").strip()
        if not name:
            continue
        if canonical in out and key in TELEMETRY_FIELD_ALIASES:
            continue
        out[canonical] = name
    return out
