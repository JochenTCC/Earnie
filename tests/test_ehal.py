"""Unit tests for EHAL M1 schemas and validate helpers."""

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
from ehal.validate import load_schema, schema_dir


def _envelope(**extra):
    base = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": "2026-07-27T12:00:00Z",
        "adapter_id": "openems-lab",
    }
    base.update(extra)
    return base


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
        grid_power_active=1500.0,
        pv_production_active=3200.0,
        ess_soc=55.0,
        ess_power=-800.0,
        evcs_active_power=11000.0,
    )
    out = validate_telemetry(doc)
    assert out["grid_power_active"] == 1500.0
    assert out["ess_power"] == -800.0


def test_telemetry_allows_grid_export_negative():
    doc = _envelope(
        grid_power_active=-2200.0,
        pv_production_active=4000.0,
        ess_soc=80.0,
    )
    assert validate_telemetry(doc)["grid_power_active"] == -2200.0


def test_telemetry_rejects_negative_pv():
    doc = _envelope(
        grid_power_active=0.0,
        pv_production_active=-1.0,
        ess_soc=50.0,
    )
    with pytest.raises(EhalValidationError):
        validate_telemetry(doc)


def test_telemetry_rejects_missing_ess_soc():
    doc = _envelope(
        grid_power_active=0.0,
        pv_production_active=0.0,
    )
    with pytest.raises(EhalValidationError):
        validate_telemetry(doc)


def test_telemetry_rejects_soc_out_of_range():
    doc = _envelope(
        grid_power_active=0.0,
        pv_production_active=0.0,
        ess_soc=101.0,
    )
    with pytest.raises(EhalValidationError):
        validate_telemetry(doc)


def test_valid_setpoint_partial_ess_charge():
    doc = _envelope(set_ess_charge_power_limit=2000.0)
    assert validate_setpoint(doc)["set_ess_charge_power_limit"] == 2000.0


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
