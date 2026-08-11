"""TypedDict models mirroring share/ehal/*.schema.json (schema_version 3)."""

from __future__ import annotations

from typing import NotRequired, TypedDict

EHAL_SCHEMA_VERSION = 3

# Legacy M1 unprefixed telemetry names — rejected, no longer remapped to §C.
REMOVED_TELEMETRY_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "grid_power_active",
        "pv_production_active",
        "ess_soc",
        "ess_power",
        "evcs_active_power",
    }
)


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
    get_evcs_soc_min_immediate: NotRequired[float | None]


class EhalSetpoint(TypedDict):
    schema_version: int
    ts: str
    adapter_id: str
    set_ess_active_power: NotRequired[float]
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
    """Validate HA entity keys: §C names only; legacy unprefixed names raise."""
    removed = sorted(
        str(key) for key in entities if str(key) in REMOVED_TELEMETRY_FIELD_NAMES
    )
    if removed:
        raise ValueError(
            "Kritischer Konfigurationsfehler: entfernte EHAL-Feldnamen "
            f"{', '.join(removed)} — kanonische §C-Namen (sens_*/set_*/get_*) verwenden."
        )
    out: dict[str, str] = {}
    for key, value in entities.items():
        name = str(value or "").strip()
        if name:
            out[str(key)] = name
    return out
