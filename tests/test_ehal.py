"""Unit tests for EHAL schema_version 3 schemas and validate helpers."""

from __future__ import annotations

import pytest

from ehal import (
    EHAL_SCHEMA_VERSION,
    EhalValidationError,
    validate_capabilities,
    validate_setpoint,
    validate_telemetry,
    validate_write_error,
)
from ehal.models import canonicalize_ha_entity_keys
from ehal.validate import load_schema, schema_dir


def _envelope(**extra):
    base = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": "2026-07-27T12:00:00Z",
        "adapter_id": "openems-lab",
    }
    base.update(extra)
    return base


def test_schema_version_is_3():
    assert EHAL_SCHEMA_VERSION == 3
    for kind in ("telemetry", "setpoint", "capabilities", "write_error"):
        assert load_schema(kind)["properties"]["schema_version"]["const"] == 3


def test_schema_files_exist():
    root = schema_dir()
    for name in (
        "telemetry.schema.json",
        "setpoint.schema.json",
        "capabilities.schema.json",
        "write_error.schema.json",
        "envelope.schema.json",
    ):
        assert (root / name).is_file()
    for kind in ("telemetry", "setpoint", "capabilities", "write_error"):
        assert load_schema(kind)["$id"].endswith(f"{kind}.schema.json")


def test_valid_telemetry_with_optional_fields():
    doc = _envelope(
        sens_grid_power_active=1500.0,
        sens_pv_production_active=3200.0,
        sens_ess_soc=55.0,
        sens_ess_power=-800.0,
        sens_evcs_active_power=11000.0,
        sens_power_consumers=2500.0,
    )
    out = validate_telemetry(doc)
    assert out["sens_grid_power_active"] == 1500.0
    assert out["sens_ess_power"] == -800.0
    assert out["sens_power_consumers"] == 2500.0


def test_telemetry_allows_grid_export_negative():
    doc = _envelope(
        sens_grid_power_active=-2200.0,
        sens_pv_production_active=4000.0,
        sens_ess_soc=80.0,
    )
    assert validate_telemetry(doc)["sens_grid_power_active"] == -2200.0


def test_telemetry_rejects_negative_pv():
    doc = _envelope(
        sens_grid_power_active=0.0,
        sens_pv_production_active=-1.0,
        sens_ess_soc=50.0,
    )
    with pytest.raises(EhalValidationError):
        validate_telemetry(doc)


def test_telemetry_rejects_missing_ess_soc():
    doc = _envelope(
        sens_grid_power_active=0.0,
        sens_pv_production_active=0.0,
    )
    with pytest.raises(EhalValidationError):
        validate_telemetry(doc)


def test_telemetry_rejects_soc_out_of_range():
    doc = _envelope(
        sens_grid_power_active=0.0,
        sens_pv_production_active=0.0,
        sens_ess_soc=101.0,
    )
    with pytest.raises(EhalValidationError):
        validate_telemetry(doc)


def test_valid_setpoint_active_power():
    doc = _envelope(set_ess_active_power=-1500.0)
    assert validate_setpoint(doc)["set_ess_active_power"] == -1500.0


def test_valid_setpoint_partial_ess_charge():
    doc = _envelope(set_ess_charge_power_limit=2000.0)
    assert validate_setpoint(doc)["set_ess_charge_power_limit"] == 2000.0


def test_valid_setpoint_evcs_mode():
    doc = _envelope(set_evcs_mode="pv")
    assert validate_setpoint(doc)["set_evcs_mode"] == "pv"


def test_valid_setpoint_evcs_mode_off():
    doc = _envelope(set_evcs_mode="off")
    assert validate_setpoint(doc)["set_evcs_mode"] == "off"


def test_valid_setpoint_ess_mode():
    doc = _envelope(set_ess_mode="auto")
    assert validate_setpoint(doc)["set_ess_mode"] == "auto"


def test_setpoint_rejects_empty_limits():
    with pytest.raises(EhalValidationError):
        validate_setpoint(_envelope())


def test_setpoint_rejects_negative_limit():
    doc = _envelope(set_ess_discharge_power_limit=-100.0)
    with pytest.raises(EhalValidationError):
        validate_setpoint(doc)


def test_valid_capabilities():
    doc = _envelope(supports_ess_write=True, supports_evcs_current=False)
    out = validate_capabilities(doc)
    assert out["supports_ess_write"] is True
    assert out["supports_evcs_current"] is False


def test_valid_write_error():
    doc = _envelope(
        failed_fields=["set_ess_charge_power_limit"],
        message="OEM write lock (HTTP 403)",
        hub_status="403",
        retryable=False,
    )
    out = validate_write_error(doc)
    assert out["failed_fields"] == ["set_ess_charge_power_limit"]
    assert out["retryable"] is False


def test_write_error_rejects_unknown_field_name():
    doc = _envelope(
        failed_fields=["target_soc"],
        message="not an EHAL field",
        retryable=True,
    )
    with pytest.raises(EhalValidationError):
        validate_write_error(doc)


def test_write_error_requires_failed_fields():
    doc = _envelope(
        failed_fields=[],
        message="empty",
        retryable=True,
    )
    with pytest.raises(EhalValidationError):
        validate_write_error(doc)


def test_canonicalize_ha_entity_keys():
    mapped = canonicalize_ha_entity_keys(
        {
            "grid_power_active": "sensor.grid",
            "sens_ess_soc": "sensor.soc",
            "pv_production_active": "sensor.pv",
        }
    )
    assert mapped["sens_grid_power_active"] == "sensor.grid"
    assert mapped["sens_pv_production_active"] == "sensor.pv"
    assert mapped["sens_ess_soc"] == "sensor.soc"
