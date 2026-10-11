"""Hub-agnostic EHAL field-membership catalogs (mapping / adapter lists).

Tuples only — no Loxone or Home Assistant imports. Transport and unit conversion
stay in the adapters and ``field_registry`` / ``ha_units``.

``PLANT_REQUIRED_READ_FIELDS`` / ``PLANT_OPTIONAL_READ_FIELDS`` in
``ehal.field_registry`` are a separate static-hub (Loxone) read-loop contract
(different membership and order) and must not be collapsed into this module.
"""
from __future__ import annotations

TELEMETRY_REQUIRED: tuple[str, ...] = (
    "sens_grid_power_active",
    "sens_pv_production_active",
    "sens_ess_soc",
)

# Intersection of HA numeric optional and static-hub optional (membership; order = HA).
TELEMETRY_OPTIONAL_CORE: tuple[str, ...] = (
    "sens_ess_power",
    "sens_evcs_active_power",
    "sens_power_consumers",
    "get_grid_export_power_limit",
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)

# HA must not numeric-read outdoor temp / absent via the optional telemetry loop.
TELEMETRY_OPTIONAL_HA: tuple[str, ...] = TELEMETRY_OPTIONAL_CORE

# Static-hub optional list — outdoor temp / absent stay in historical mid-tuple order.
TELEMETRY_OPTIONAL_STATIC_HUB: tuple[str, ...] = (
    "sens_ess_power",
    "sens_evcs_active_power",
    "sens_power_consumers",
    "sens_temperature_outside",
    "sens_absent_mode",
    "get_grid_export_power_limit",
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)

# Side-channel binary plant sensors (not part of EHAL telemetry wire / numeric read).
TELEMETRY_BINARY_OPTIONAL: tuple[str, ...] = (
    "sens_absent_mode",
)

# Slot-Ist ΔkWh side channel — not part of EHAL telemetry wire.
TELEMETRY_ENERGY_OPTIONAL: tuple[str, ...] = (
    "sens_pv_energy",
    "sens_grid_energy_import",
    "sens_grid_energy_export",
)

SETPOINT_FIELDS: tuple[str, ...] = (
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_mode",
    "set_ess_source_select",
    "set_evcs_max_current",
    "set_evcs_mode",
    "set_grid_export_power_limit",
)

HA_MAP_FIELDS: tuple[str, ...] = (
    TELEMETRY_REQUIRED
    + TELEMETRY_OPTIONAL_HA
    + TELEMETRY_BINARY_OPTIONAL
    + TELEMETRY_ENERGY_OPTIONAL
    + SETPOINT_FIELDS
)

STATIC_HUB_MAP_FIELDS: tuple[str, ...] = (
    TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL_STATIC_HUB + SETPOINT_FIELDS
)

# Temporary aliases (rename cleanup); remove once all imports use the new names.
TELEMETRY_OPTIONAL_LOXONE = TELEMETRY_OPTIONAL_STATIC_HUB
LOXONE_MAP_FIELDS = STATIC_HUB_MAP_FIELDS
