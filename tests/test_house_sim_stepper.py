"""Unit tests for house_sim physics stepper (SoC, PV series, optional thermal)."""
from __future__ import annotations

import pytest

from house_sim.archetype import load_archetype, project_physics_to_store
from house_sim.stepper import initial_physics, run_ticks, step_physics


def test_initial_physics_from_fixture():
    package = load_archetype("evcc_en")
    state = initial_physics(package)
    assert state.soc_pct == pytest.approx(55.0)
    assert state.pv_kw == pytest.approx(0.8)
    assert state.temp_c == pytest.approx(42.0)


def test_charge_raises_soc():
    package = load_archetype("evcc_en")
    store = package.build_store()
    store.set_state("input_number.ess_active_power_w", "-2000")  # charge 2 kW
    state = initial_physics(package)
    # 2 kW charge × 0.5 h / 10 kWh × 100 = +10 % SoC
    nxt = step_physics(state, package=package, store=store, dt_h=0.5)
    assert nxt.soc_pct == pytest.approx(65.0)
    assert nxt.ess_power_w == pytest.approx(-2000.0)
    assert nxt.pv_kw == pytest.approx(1.2)  # series tick 1


def test_discharge_lowers_soc():
    package = load_archetype("evcc_en")
    store = package.build_store()
    store.set_state("input_number.ess_active_power_w", "4000")  # discharge 4 kW
    state = initial_physics(package)
    nxt = step_physics(state, package=package, store=store, dt_h=0.25)
    # 4 kW × 0.25 h / 10 kWh × 100 = −10 %
    assert nxt.soc_pct == pytest.approx(45.0)


def test_soc_clamped_at_100():
    package = load_archetype("evcc_en")
    store = package.build_store()
    store.set_state("input_number.ess_active_power_w", "-10000")
    state = initial_physics(package)
    # Force near-full then overshoot
    from dataclasses import replace

    state = replace(state, soc_pct=99.0)
    nxt = step_physics(state, package=package, store=store, dt_h=1.0)
    assert nxt.soc_pct == pytest.approx(100.0)


def test_pv_series_advances_and_clamps():
    package = load_archetype("evcc_en")
    store = package.build_store()
    state = run_ticks(package, store, n_ticks=10, dt_h=0.1)
    assert state.tick == 10
    assert state.pv_kw == pytest.approx(package.pv_series_kw[-1])


def test_thermal_tick_moves_temp():
    package = load_archetype("evcc_en")
    store = package.build_store()
    state = initial_physics(package)
    assert state.temp_c is not None
    nxt = step_physics(state, package=package, store=store, dt_h=1.0)
    # heat_kw=0, ambient cooler → temp drops
    assert nxt.temp_c is not None
    assert nxt.temp_c < state.temp_c
    project_physics_to_store(store, package=package, physics=nxt.as_dict())
    assert store.numeric_state("sensor.house_sim_buffer_temp") == pytest.approx(
        nxt.temp_c
    )
