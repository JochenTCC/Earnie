"""Battery views of a house with several batteries: MILP view vs. plant battery."""
from __future__ import annotations

import pytest

from optimizer.milp_horizon import (
    plant_battery_params,
    plant_soc_percent,
    primary_battery_with_plant_power,
)
from optimizer.sim_horizon_chart_soc import plant_start_soc


def _battery(ess_id: str, **overrides) -> dict:
    battery = {
        "id": ess_id,
        "label": ess_id.upper(),
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "max_power_kw": 5.0,
        "efficiency": 0.95,
        "standby_power_kw": 0.05,
        "control": "full",
    }
    battery.update(overrides)
    return battery


def test_two_equal_batteries_double_capacity_and_power():
    plant = plant_battery_params([_battery("a"), _battery("b")])

    assert plant["battery_capacity_kwh"] == pytest.approx(20.0)
    assert plant["max_charge_power_kw"] == pytest.approx(10.0)
    assert plant["max_discharge_power_kw"] == pytest.approx(10.0)
    assert plant["max_power_kw"] == pytest.approx(10.0)
    assert plant["standby_power_kw"] == pytest.approx(0.1)
    assert plant["min_soc"] == pytest.approx(10.0)
    assert plant["max_soc"] == pytest.approx(100.0)
    assert plant["efficiency"] == pytest.approx(0.95)
    assert plant["control"] == "full"


def test_two_different_batteries_keep_usable_energy():
    small = _battery(
        "a", battery_capacity_kwh=5.0, min_soc=20.0, max_soc=90.0, efficiency=0.90,
        max_charge_power_kw=2.0, max_discharge_power_kw=3.0, max_power_kw=3.0,
    )
    large = _battery("b", battery_capacity_kwh=15.0, min_soc=10.0, max_soc=100.0, efficiency=0.98)

    plant = plant_battery_params([small, large])

    assert plant["battery_capacity_kwh"] == pytest.approx(20.0)
    # Energy limits add up: 1.0 + 1.5 kWh at the bottom, 4.5 + 15.0 kWh at the top.
    assert plant["min_soc"] / 100.0 * 20.0 == pytest.approx(2.5)
    assert plant["max_soc"] / 100.0 * 20.0 == pytest.approx(19.5)
    assert plant["efficiency"] == pytest.approx((5.0 * 0.90 + 15.0 * 0.98) / 20.0)
    assert plant["max_charge_power_kw"] == pytest.approx(7.0)
    assert plant["max_discharge_power_kw"] == pytest.approx(8.0)
    assert plant["max_power_kw"] == pytest.approx(8.0)


def test_single_battery_is_unchanged():
    battery = _battery("a", extra_key="kept")

    plant = plant_battery_params([battery])

    assert plant == primary_battery_with_plant_power([battery])
    assert plant == battery
    assert [type(plant[key]) for key in battery] == [type(value) for value in battery.values()]


def test_empty_list_is_a_battery_without_capacity():
    plant = plant_battery_params([])

    assert plant == primary_battery_with_plant_power([])
    assert plant["battery_capacity_kwh"] == 0.0
    assert plant["max_power_kw"] == 0.0
    assert plant["control"] == "full"


def test_mixed_control_modes_raise():
    with pytest.raises(ValueError, match="different control modes"):
        plant_battery_params([_battery("a"), _battery("b", control="read_only")])


def test_milp_view_keeps_first_battery_capacity_and_limits():
    first = _battery("a", battery_capacity_kwh=5.0, min_soc=20.0)
    view = primary_battery_with_plant_power([first, _battery("b")])

    assert view["battery_capacity_kwh"] == 5.0
    assert view["min_soc"] == 20.0
    assert view["max_power_kw"] == pytest.approx(10.0)
    assert view["standby_power_kw"] == pytest.approx(0.1)


def test_plant_soc_is_energy_weighted():
    batteries = [_battery("a", battery_capacity_kwh=5.0), _battery("b", battery_capacity_kwh=15.0)]

    assert plant_soc_percent(batteries, {"a": 40.0, "b": 80.0}) == pytest.approx(70.0)


def test_plant_soc_requires_every_battery():
    with pytest.raises(ValueError, match="'b'"):
        plant_soc_percent([_battery("a"), _battery("b")], {"a": 40.0})


def test_plant_start_soc_single_battery_is_initial_soc():
    assert plant_start_soc([_battery("a")], 37.0, None) == 37.0
    assert plant_start_soc([_battery("a")], 37.0, {"a": 55.0}) == 37.0


def test_plant_start_soc_several_batteries(monkeypatch):
    monkeypatch.setattr("optimizer.milp_defaults._default_inverter_params", lambda: [])
    batteries = [_battery("a", battery_capacity_kwh=5.0), _battery("b", battery_capacity_kwh=15.0)]

    assert plant_start_soc(batteries, 40.0, {"a": 40.0, "b": 80.0}) == pytest.approx(70.0)
    with pytest.raises(ValueError, match="no SoC for house battery"):
        plant_start_soc(batteries, 40.0, None)


def test_open_loop_books_the_plant_soc(monkeypatch):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    from optimizer.simulation import simulate_horizon

    batteries = [
        _battery("a", battery_capacity_kwh=5.0, max_charge_power_kw=2.5,
                 max_discharge_power_kw=2.5, max_power_kw=2.5, standby_power_kw=0.0,
                 battery_wear={"enabled": False}),
        _battery("b", battery_capacity_kwh=10.0, standby_power_kw=0.0,
                 battery_wear={"enabled": False}),
    ]
    matrix = [
        {"expected_p_pv": 3.0, "expected_p_act": 1.0, "k_act": 20.0, "k_push_act": 5.0, "hour": 12},
        {"expected_p_pv": 2.0, "expected_p_act": 1.5, "k_act": 25.0, "k_push_act": 5.0, "hour": 13},
    ]

    rows = simulate_horizon(
        matrix,
        40.0,
        battery_params=batteries,
        k_push=5.0,
        verbose=False,
        commit_hours=len(matrix),
        current_soc_by_id={"a": 40.0, "b": 60.0},
    )

    # (5 kWh · 40 % + 10 kWh · 60 %) / 15 kWh
    assert rows[0]["Simulierter SoC (%)"] == pytest.approx(53.3, abs=0.05)
    with pytest.raises(ValueError, match="no SoC for house battery"):
        simulate_horizon(
            matrix, 40.0, battery_params=batteries, k_push=5.0, verbose=False,
            commit_hours=len(matrix),
        )
