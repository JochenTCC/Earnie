"""HouseSim heat pump controller (HeatControl P2): enable and SG-Ready state."""
from __future__ import annotations

import pytest

from ehal.heat_fields import sg_ready_state_for_plan
from house_sim.core.heat_pump import (
    HeatPumpStoreParams,
    HeatPumpStoreState,
    controller_target_c,
    step_heat_pump_store,
)

PARAMS = HeatPumpStoreParams(
    capacity_kwh_per_k=1.0,
    heat_loss_kw_per_k=0.005,
    heat_power_kw=8.0,
    cop=4.0,
    setpoint_c=33.0,
    tolerance_c=2.0,
    boost_k=22.0,
    max_c=60.0,
)

# A day of Earnie's level-0 plan per quarter hour: cheap slots in the night and at noon.
ENABLE_PLAN = [1 if (8 <= q < 20 or 44 <= q < 56) else 0 for q in range(96)]


def _run(*, enables=None, states=None, start=34.0, demand_kw=2.0):
    state = HeatPumpStoreState(temp_c=start)
    temps, energy = [], 0.0
    steps = enables if enables is not None else states
    for value in steps:
        kwargs = {"enable": value} if enables is not None else {"sg_ready_state": value}
        state, kwh = step_heat_pump_store(
            PARAMS, state, demand_kw=demand_kw, ambient_c=15.0, dt_h=0.25, **kwargs
        )
        temps.append(state.temp_c)
        energy += kwh
    return temps, energy


def test_state_driven_run_matches_enable_driven_run():
    """P2 done criterion: the state derived from the plan gives the enable's trajectory."""
    by_enable = _run(enables=ENABLE_PLAN)
    by_state = _run(states=[sg_ready_state_for_plan(bool(e)) for e in ENABLE_PLAN])
    assert by_state == by_enable


def test_state_3_charges_to_setpoint_plus_boost():
    temps, _ = _run(states=[3] * 24)
    assert max(temps) == pytest.approx(55.0)


def test_state_2_keeps_the_normal_band():
    temps, energy = _run(states=[2] * 96, start=32.0)
    assert energy > 0.0
    assert min(temps) >= 31.0 - 0.5  # one step of 2 kW demand below the band at most
    assert max(temps) <= 33.0 + 1e-9


def test_state_1_locks_the_generator():
    temps, energy = _run(states=[1] * 8)
    assert energy == 0.0
    assert temps[-1] < 34.0


def test_state_4_starts_at_once_and_charges_to_max():
    # At 54 °C state 3 waits (above 55 − 2), state 4 starts at once.
    state3 = step_heat_pump_store(
        PARAMS, HeatPumpStoreState(54.0), demand_kw=0.0, ambient_c=15.0, dt_h=0.25,
        sg_ready_state=3,
    )
    state4 = step_heat_pump_store(
        PARAMS, HeatPumpStoreState(54.0), demand_kw=0.0, ambient_c=15.0, dt_h=0.25,
        sg_ready_state=4,
    )
    assert state3[1] == 0.0
    assert state4[1] > 0.0
    assert controller_target_c(PARAMS, 4) == 60.0


def test_one_request_source_per_step():
    with pytest.raises(ValueError, match="exactly one"):
        step_heat_pump_store(
            PARAMS, HeatPumpStoreState(34.0), demand_kw=0.0, ambient_c=15.0, dt_h=0.25,
            enable=1, sg_ready_state=3,
        )
    with pytest.raises(ValueError, match="1..4"):
        step_heat_pump_store(
            PARAMS, HeatPumpStoreState(34.0), demand_kw=0.0, ambient_c=15.0, dt_h=0.25,
            sg_ready_state=5,
        )


def test_state_4_without_max_fails_loud():
    params = HeatPumpStoreParams(
        capacity_kwh_per_k=1.0, heat_loss_kw_per_k=0.0, heat_power_kw=8.0, cop=4.0,
        setpoint_c=33.0, tolerance_c=2.0,
    )
    with pytest.raises(ValueError, match="max_c"):
        controller_target_c(params, 4)
