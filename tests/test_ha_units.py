"""HA unit helpers: physical quantity check and conversion factors (YAML / HouseSim)."""
from __future__ import annotations

import pytest

from integrations.ha_units import (
    UnitMismatchError,
    describe_conversion,
    from_ehal,
    to_ehal,
    unit_check,
)


@pytest.mark.parametrize(
    ("field", "unit", "device_class", "expected"),
    [
        ("sens_grid_power_active", "kW", "power", "ok"),
        ("sens_grid_power_active", "W", None, "ok"),
        ("sens_grid_power_active", "kWh", "energy", "mismatch"),
        ("sens_grid_power_active", "kW", "energy", "mismatch"),
        ("sens_ess_power", "%", "battery", "mismatch"),
        ("sens_ess_power", None, None, "unknown"),
        ("sens_pv_energy", "Wh", "energy", "ok"),
        ("sens_pv_energy", "W", "power", "mismatch"),
        ("sens_ess_soc", "%", "battery", "ok"),
        ("set_evcs_max_current", "A", None, "ok"),
        ("set_evcs_max_current", "W", None, "mismatch"),
        ("set_ess_mode", None, None, "free"),
        ("sens_grid_power_active", "VA", None, "mismatch"),
    ],
)
def test_unit_check(field, unit, device_class, expected):
    assert unit_check(field, unit, device_class=device_class) == expected


def test_factors_follow_entity_unit():
    assert to_ehal("sens_grid_power_active", 1.5, "kW") == pytest.approx(1500.0)
    assert to_ehal("sens_grid_power_active", 1.5, "kilowatt") == pytest.approx(1500.0)
    assert to_ehal("sens_pv_energy", 2500.0, "Wh") == pytest.approx(2.5)
    assert to_ehal("sens_pv_energy", 0.5, "MWh") == pytest.approx(500.0)
    assert to_ehal("sens_grid_power_active", 700.0, None) == pytest.approx(700.0)
    assert from_ehal("set_ess_active_power", -1500.0, "kW") == pytest.approx(-1.5)
    assert from_ehal("set_evcs_max_current", 16.0, "A") == pytest.approx(16.0)
    assert to_ehal("set_ess_mode", 2.0, "kW") == pytest.approx(2.0)  # free field


def test_wrong_quantity_raises():
    with pytest.raises(UnitMismatchError):
        to_ehal("sens_grid_power_active", 1.0, "kWh")
    with pytest.raises(UnitMismatchError):
        from_ehal("set_ess_charge_power_limit", 1000.0, "%")


def test_describe_conversion():
    assert describe_conversion("sens_grid_power_active", "kW") == "kW → W (×1000)"
    assert describe_conversion("sens_pv_energy", "Wh") == "Wh → kWh (×0.001)"
    assert describe_conversion("sens_grid_power_active", "W") == ""
    assert describe_conversion("sens_grid_power_active", "kWh") == ""


def test_quantity_units_table_stable():
    from integrations.ha_units import QUANTITY_UNITS

    assert QUANTITY_UNITS["power"]["kw"] == 1000.0
    assert QUANTITY_UNITS["energy"]["wh"] == 0.001
