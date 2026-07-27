"""TypedDict models mirroring share/ehal/*.schema.json (M1)."""

from __future__ import annotations

from typing import NotRequired, TypedDict

EHAL_SCHEMA_VERSION = 1


class EhalEnvelope(TypedDict):
    schema_version: int
    ts: str
    adapter_id: str


class EhalTelemetry(TypedDict):
    schema_version: int
    ts: str
    adapter_id: str
    grid_power_active: float
    pv_production_active: float
    ess_soc: float
    ess_power: NotRequired[float | None]
    evcs_active_power: NotRequired[float | None]


class EhalSetpoint(TypedDict):
    schema_version: int
    ts: str
    adapter_id: str
    set_ess_charge_power_limit: NotRequired[float]
    set_ess_discharge_power_limit: NotRequired[float]
    set_evcs_max_current: NotRequired[float]


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
