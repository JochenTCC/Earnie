"""Unit tests for house_sim.core weather PV and scenario overlays."""
from __future__ import annotations

from dataclasses import replace

import pytest

from house_sim.core.archetype import load_archetype
from house_sim.core.physics import (
    EssSetpoints,
    ScenarioOverlay,
    initial_physics,
    step_physics,
)
from house_sim.core.weather_pv import pv_kw_from_weather


def test_pv_kw_from_weather_zero_below_horizon():
    assert pv_kw_from_weather(10.0, 0.0, -5.0) == 0.0
    assert pv_kw_from_weather(10.0, 0.0, 0.0) == 0.0


def test_pv_kw_from_weather_clear_vs_cloudy():
    clear = pv_kw_from_weather(10.0, 0.0, 90.0)
    cloudy = pv_kw_from_weather(10.0, 100.0, 90.0)
    assert clear == pytest.approx(10.0)
    assert cloudy == pytest.approx(2.5)
    assert cloudy < clear


def test_cloud_pass_scales_pv():
    package = load_archetype("evcc_en")
    state = initial_physics(package)
    overlay = ScenarioOverlay()
    overlay.apply_cloud_pass(minutes=30, scale=0.2)
    nxt = step_physics(
        state,
        package=package,
        setpoints=EssSetpoints(),
        dt_h=0.25,
        overlay=overlay,
    )
    # series tick 1 = 1.2 → scaled 0.24
    assert nxt.pv_kw == pytest.approx(1.2 * 0.2)
    assert overlay.cloud_pass_remaining_h == pytest.approx(0.5 - 0.25)


def test_car_arrives_raises_load_and_evcs():
    package = load_archetype("evcc_en")
    state = initial_physics(package)
    overlay = ScenarioOverlay()
    overlay.car_arrives(7000.0)
    nxt = step_physics(
        state,
        package=package,
        setpoints=EssSetpoints(),
        dt_h=0.25,
        overlay=overlay,
    )
    assert nxt.evcs_power_w == pytest.approx(7000.0)
    # base load 1.5 + 7 kW EVCS, pv tick1 1.2 → grid_kw = 8.5 - 1.2 = 7.3
    assert nxt.grid_power_w == pytest.approx(7300.0)


def test_set_soc_via_replace_and_step():
    package = load_archetype("evcc_en")
    state = replace(initial_physics(package), soc_pct=20.0)
    nxt = step_physics(
        state, package=package, setpoints=EssSetpoints(), dt_h=0.25
    )
    assert nxt.soc_pct == pytest.approx(20.0)


def test_battery_energy_counters_follow_ess_sign():
    package = load_archetype("evcc_en")
    state = initial_physics(package)
    assert state.ess_charge_energy_kwh == 0.0
    assert state.ess_discharge_energy_kwh == 0.0
    charged = step_physics(
        state,
        package=package,
        setpoints=EssSetpoints(active_power_w=-2000.0),
        dt_h=0.5,
    )
    assert charged.ess_charge_energy_kwh == pytest.approx(1.0)
    assert charged.ess_discharge_energy_kwh == 0.0
    discharged = step_physics(
        charged,
        package=package,
        setpoints=EssSetpoints(active_power_w=3000.0),
        dt_h=0.25,
    )
    assert discharged.ess_charge_energy_kwh == pytest.approx(1.0)
    assert discharged.ess_discharge_energy_kwh == pytest.approx(0.75)


def test_battery_energy_counters_projected_to_store():
    from house_sim.core.archetype import project_physics_to_store

    package = load_archetype("evcc_en")
    written: dict[str, str] = {}

    class _Store:
        def get(self, entity_id):
            return None

        def set_state(self, entity_id, state):
            written[entity_id] = state

    physics = replace(
        initial_physics(package),
        ess_charge_energy_kwh=1.5,
        ess_discharge_energy_kwh=0.5,
    )
    project_physics_to_store(store=_Store(), package=package, physics=physics.as_dict())
    assert float(written["sensor.evcc_battery_charge_energy"]) == pytest.approx(1.5)
    assert float(written["sensor.evcc_battery_discharge_energy"]) == pytest.approx(0.5)
