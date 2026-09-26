"""HA unit mapping: physical quantity check (rule 1) and runtime factors (rule 2)."""
from __future__ import annotations

import pytest

from house_sim.archetype import load_archetype
from integrations.ha_ehal_mapping import (
    binding_conversion_hint,
    binding_unit_issues,
    compatible_entity_ids,
    heuristic_propose,
)
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


_ROWS = [
    {"entity_id": "sensor.grid_kw", "unit": "kW", "device_class": "power"},
    {"entity_id": "sensor.grid_kwh", "unit": "kWh", "device_class": "energy"},
    {"entity_id": "sensor.soc", "unit": "%", "device_class": "battery"},
    {"entity_id": "input_number.helper", "unit": None, "device_class": None},
]


def test_compatible_entity_ids_drops_other_quantities():
    assert compatible_entity_ids("sens_grid_power_active", _ROWS) == [
        "sensor.grid_kw",
        "input_number.helper",
    ]
    assert compatible_entity_ids("sens_grid_energy_import", _ROWS) == [
        "sensor.grid_kwh",
        "input_number.helper",
    ]


def test_binding_unit_issues_and_hint():
    issues = binding_unit_issues(
        {"sens_grid_power_active": "sensor.grid_kwh", "sens_ess_soc": "sensor.soc"}, _ROWS
    )
    assert len(issues) == 1
    assert "sens_grid_power_active" in issues[0] and "kWh" in issues[0]
    assert binding_conversion_hint("sens_grid_power_active", "sensor.grid_kw", _ROWS) == (
        "kW → W (×1000)"
    )


def test_validate_mapping_save_rejects_wrong_quantity():
    from ui.ehal_ha_mapping import _validate_mapping_save

    ehal_map = {
        "sens_grid_power_active": "sensor.grid_kwh",
        "sens_pv_production_active": "sensor.grid_kw",
        "sens_ess_soc": "sensor.soc",
    }
    error = _validate_mapping_save("plant", ehal_map, _ROWS)
    assert error is not None and "Einheit passt nicht" in error
    ehal_map["sens_grid_power_active"] = "sensor.grid_kw"
    assert _validate_mapping_save("plant", ehal_map, _ROWS) is None


def _scan_rows(name: str) -> list[dict]:
    package = load_archetype(name)
    return [
        {
            "entity_id": e["entity_id"],
            "domain": e["entity_id"].split(".", 1)[0],
            "unit": e["attributes"].get("unit_of_measurement"),
            "device_class": e["attributes"].get("device_class"),
            "state_class": e["attributes"].get("state_class"),
            "friendly_name": e["attributes"].get("friendly_name"),
        }
        for e in package.entities
    ]


@pytest.mark.parametrize("name", ("evcc_en", "fronius_de", "huawei_en", "sma_keba"))
def test_propose_never_crosses_physical_quantities(name):
    rows = _scan_rows(name)
    by_id = {r["entity_id"]: r for r in rows}
    for field, proposal in heuristic_propose(rows).items():
        row = by_id[proposal["entity_id"]]
        assert unit_check(field, row["unit"], device_class=row["device_class"]) != "mismatch"


@pytest.mark.parametrize("name", ("evcc_en", "fronius_de", "huawei_en", "sma_keba"))
def test_golden_maps_are_physically_consistent(name):
    package = load_archetype(name)
    assert binding_unit_issues(dict(package.ehal_entities), _scan_rows(name)) == []


def test_house_sim_unit_factors_match_ha_quantities():
    from house_sim.core.archetype import UNIT_FACTORS
    from integrations.ha_units import QUANTITY_UNITS

    for quantity in ("power", "energy", "percent"):
        assert UNIT_FACTORS[quantity] == QUANTITY_UNITS[quantity]
