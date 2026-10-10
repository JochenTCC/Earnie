"""Unit tests for ehal.field_registry hub conversion (read + write)."""

from __future__ import annotations

import pytest

from ehal.field_registry import (
    apply_loxone_read,
    apply_loxone_write,
    apply_openems_read,
    apply_openems_write,
    clear_loxone_spec_cache,
    loxone_spec,
    openems_spec,
    require_loxone_write,
)


@pytest.fixture(autouse=True)
def _clear_registry_cache() -> None:
    clear_loxone_spec_cache()
    yield
    clear_loxone_spec_cache()


def test_loxone_spec_grid_power() -> None:
    spec = loxone_spec("sens_grid_power_active")
    assert spec is not None
    assert spec.factor == 1000
    assert spec.read_required is True
    assert apply_loxone_read(-1.5, spec) == pytest.approx(-1500.0)


def test_loxone_spec_pv_clamp() -> None:
    spec = loxone_spec("sens_pv_production_active")
    assert spec is not None
    assert apply_loxone_read(-0.1, spec) == pytest.approx(0.0)
    assert apply_loxone_read(2.0, spec) == pytest.approx(2000.0)


def test_loxone_spec_ess_power_sign() -> None:
    spec = loxone_spec("sens_ess_power")
    assert spec is not None
    assert spec.read_required is True
    assert apply_loxone_read(-0.5, spec) == pytest.approx(-500.0)


def test_loxone_spec_soc_passthrough() -> None:
    spec = loxone_spec("sens_ess_soc")
    assert spec is not None
    assert apply_loxone_read(55.0, spec) == pytest.approx(55.0)


def test_loxone_spec_soc_limits_clamp() -> None:
    spec = loxone_spec("get_ess_soc_min")
    assert spec is not None
    assert apply_loxone_read(-5.0, spec) == pytest.approx(0.0)
    assert apply_loxone_read(150.0, spec) == pytest.approx(100.0)


def test_loxone_spec_omit_if_negative() -> None:
    for field in (
        "get_grid_export_power_limit",
        "get_ess_max_charge_power",
        "get_ess_max_discharge_power",
    ):
        spec = loxone_spec(field)
        assert spec is not None
        assert apply_loxone_read(-1.0, spec) is None
        assert apply_loxone_read(3.5, spec) == pytest.approx(3500.0)


def test_loxone_spec_bad_raw_omits() -> None:
    spec = loxone_spec("get_ess_soc_max")
    assert spec is not None
    assert apply_loxone_read(None, spec) is None
    assert apply_loxone_read("x", spec) is None


def test_loxone_write_active_power_inverse() -> None:
    spec = loxone_spec("set_ess_active_power")
    assert spec is not None
    assert apply_loxone_write(-1500.0, spec) == pytest.approx(-1.5)
    assert require_loxone_write("set_ess_active_power", 2000.0) == pytest.approx(2.0)


def test_loxone_write_limit_clamps_negative() -> None:
    for field in (
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
        "set_grid_export_power_limit",
    ):
        assert require_loxone_write(field, 2000.0) == pytest.approx(2.0)
        assert require_loxone_write(field, -100.0) == pytest.approx(0.0)


def test_loxone_write_roundtrip_active() -> None:
    spec = loxone_spec("set_ess_active_power")
    assert spec is not None
    hub = apply_loxone_write(-1500.0, spec)
    assert apply_loxone_read(hub, spec) == pytest.approx(-1500.0)


def test_openems_grid_sign_flip() -> None:
    spec = openems_spec("sens_grid_power_active")
    assert spec is not None
    assert apply_openems_read(-77, spec) == pytest.approx(77.0)
    assert apply_openems_read(50, spec) == pytest.approx(-50.0)


def test_openems_limit_write_polarity() -> None:
    charge = openems_spec("set_ess_charge_power_limit")
    discharge = openems_spec("set_ess_discharge_power_limit")
    assert charge is not None and discharge is not None
    assert apply_openems_write(2000.0, charge) == pytest.approx(-2000.0)
    assert apply_openems_write(1500.0, discharge) == pytest.approx(1500.0)
