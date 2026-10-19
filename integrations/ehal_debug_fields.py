"""EHAL Live-Lesen / Live-Schreiben field tables (pure data, split from ``ehal_debug_mapping``)."""
from __future__ import annotations

from ehal.field_catalog import (
    SETPOINT_FIELDS,
    TELEMETRY_OPTIONAL_STATIC_HUB as TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
)

# Unmapped Mapping cells stay empty (not an em-dash).
_MAPPING_EMPTY = ""
_MAPPING_DERIVED = "—(abgeleitet)"

# House-wide plant reads (grid kinds are storage-bare; Live shows grid.meter.*).
PLANT_HOUSE_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_grid_power_active",
    "sens_power_consumers",
    "sens_temperature_outside",
    "sens_absent_mode",
    "get_grid_export_power_limit",
    "sens_pv_energy",
    "sens_grid_energy_import",
    "sens_grid_energy_export",
)

# Bare plant ESS kinds — Live rows only when no ehal-mappable battery exists.
# SoC is never plant-flat (schema_version 4); only entity-scoped ess.{id}.sens_ess_soc.
PLANT_ESS_LIVE_READ_KINDS: tuple[str, ...] = (
    "sens_ess_power",
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)

# Union for callers that still inspect the full plant read set.
PLANT_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_grid_power_active",
    "sens_ess_power",
    "sens_power_consumers",
    "sens_temperature_outside",
    "sens_absent_mode",
    "get_grid_export_power_limit",
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
    "sens_pv_energy",
    "sens_grid_energy_import",
    "sens_grid_energy_export",
)

CONSUMER_ENERGY_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_energy_total",
)

# Per-battery entity-scoped read kinds (2.7.m).
BATTERY_ESS_LIVE_READ_KINDS: tuple[str, ...] = (
    "sens_ess_soc",
    "sens_ess_power",
    "sens_ess_energy_charge",
    "sens_ess_energy_discharge",
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)

BATTERY_ESS_LIVE_WRITE_KINDS: tuple[str, ...] = (
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_mode",
)

BATTERY_SOURCE_SELECT_KIND = "set_ess_source_select"

# Per-inverter entity-scoped read/write kinds (2.7.l P4).
INVERTER_LIVE_READ_KINDS: tuple[str, ...] = (
    "sens_inv_power_ac",
    "sens_inv_power_pv",
    "get_inv_max_ac_power",
    "get_inv_max_pv_power",
)

INVERTER_LIVE_WRITE_KINDS: tuple[str, ...] = ("set_inv_ac_power_limit",)

# Per-PV-system entity-scoped read kinds.
PV_LIVE_READ_KINDS: tuple[str, ...] = ("sens_pv_production_active",)

PLANT_LIVE_WRITE_FIELDS: tuple[str, ...] = (
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_mode",
    "set_grid_export_power_limit",
)
EV_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_evcs_active_power",
    "sens_evcs_connected",
    "sens_evcs_soc_act",
    "get_evcs_nominal_current",
    "sens_evcs_bat_capacity",
    "get_evcs_ready_by_time",
    "get_evcs_limit_soc",
    "get_evcs_soc_min_immediate",
)

EV_LIVE_WRITE_FIELDS: tuple[str, ...] = (
    "set_evcs_max_current",
    "set_evcs_mode",
)

FILTER_LIVE_READ_FIELDS: tuple[str, ...] = (
    "get_filter_remaining_hours",
    "sens_filter_active",
    "get_filter_native_start_hour",
    "get_filter_native_duration_hours",
)

THERMAL_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_temperature_water",
    "get_temperature_water_setpoint",
    "get_temperature_tolerance_c",
    "sens_heating_active",
)

THERMAL_ANNUAL_LIVE_READ_FIELDS: tuple[str, ...] = (
    "sens_temperature_heat_storage",
    "sens_temperature_heat_storage_low",
)

NETWORK_LIVE_READ_FIELDS: tuple[str, ...] = TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL
NETWORK_LIVE_WRITE_FIELDS: tuple[str, ...] = SETPOINT_FIELDS
