"""Identity checks for hub-agnostic EHAL field-membership catalogs."""
from __future__ import annotations

from ehal.field_catalog import (
    HA_MAP_FIELDS,
    SETPOINT_FIELDS,
    STATIC_HUB_MAP_FIELDS,
    TELEMETRY_BINARY_OPTIONAL,
    TELEMETRY_ENERGY_OPTIONAL,
    TELEMETRY_ESS_SOC_KIND,
    TELEMETRY_OPTIONAL_CORE,
    TELEMETRY_OPTIONAL_HA,
    TELEMETRY_OPTIONAL_STATIC_HUB,
    TELEMETRY_REQUIRED,
)


def test_telemetry_required_membership():
    assert TELEMETRY_REQUIRED == (
        "sens_grid_power_active",
        "sens_pv_production_active",
    )


def test_ha_optional_is_core_without_outdoor_or_absent():
    assert TELEMETRY_OPTIONAL_HA == TELEMETRY_OPTIONAL_CORE
    assert "sens_temperature_outside" not in TELEMETRY_OPTIONAL_HA
    assert "sens_absent_mode" not in TELEMETRY_OPTIONAL_HA
    assert TELEMETRY_OPTIONAL_CORE == (
        "sens_ess_power",
        "sens_evcs_active_power",
        "sens_power_consumers",
        "get_grid_export_power_limit",
        "get_ess_soc_min",
        "get_ess_soc_max",
        "get_ess_max_charge_power",
        "get_ess_max_discharge_power",
    )


def test_static_hub_optional_historical_order():
    assert TELEMETRY_OPTIONAL_STATIC_HUB == (
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
    assert set(TELEMETRY_OPTIONAL_CORE).issubset(TELEMETRY_OPTIONAL_STATIC_HUB)
    assert set(TELEMETRY_OPTIONAL_STATIC_HUB) - set(TELEMETRY_OPTIONAL_CORE) == {
        "sens_temperature_outside",
        "sens_absent_mode",
    }


def test_setpoint_and_energy_tuples():
    assert SETPOINT_FIELDS == (
        "set_ess_active_power",
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
        "set_ess_mode",
        "set_ess_source_select",
        "set_evcs_max_current",
        "set_evcs_mode",
        "set_grid_export_power_limit",
    )
    assert TELEMETRY_ENERGY_OPTIONAL == (
        "sens_pv_energy",
        "sens_grid_energy_import",
        "sens_grid_energy_export",
    )
    assert TELEMETRY_BINARY_OPTIONAL == ("sens_absent_mode",)


def test_ha_map_fields_concatenation():
    assert TELEMETRY_ESS_SOC_KIND == ("sens_ess_soc",)
    assert HA_MAP_FIELDS == (
        TELEMETRY_REQUIRED
        + TELEMETRY_ESS_SOC_KIND
        + TELEMETRY_OPTIONAL_HA
        + TELEMETRY_BINARY_OPTIONAL
        + TELEMETRY_ENERGY_OPTIONAL
        + SETPOINT_FIELDS
    )


def test_static_hub_map_fields_concatenation():
    assert STATIC_HUB_MAP_FIELDS == (
        TELEMETRY_REQUIRED
        + TELEMETRY_ESS_SOC_KIND
        + TELEMETRY_OPTIONAL_STATIC_HUB
        + SETPOINT_FIELDS
    )


def test_adapter_reexports_match_catalog():
    from integrations import ha_adapter, loxone_adapter, loxone_ehal_mapping

    assert ha_adapter.TELEMETRY_REQUIRED is TELEMETRY_REQUIRED
    assert ha_adapter.TELEMETRY_OPTIONAL is TELEMETRY_OPTIONAL_HA
    assert ha_adapter.SETPOINT_FIELDS is SETPOINT_FIELDS
    assert loxone_adapter.SETPOINT_FIELDS is SETPOINT_FIELDS
    assert loxone_ehal_mapping.TELEMETRY_OPTIONAL is TELEMETRY_OPTIONAL_STATIC_HUB
    assert loxone_ehal_mapping.EHAL_MAP_FIELDS is STATIC_HUB_MAP_FIELDS
