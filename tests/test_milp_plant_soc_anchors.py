"""MILP SoC anchors (terminal, SE hold) bind the energy of all house batteries, not the first."""
from __future__ import annotations

import pytest

import optimizer.simulation as simulation
from optimizer.milp import milp_horizon_schedule

START_SOC_BY_ID = {"a": 40.0, "b": 60.0}
# a: 5 kWh at 40 % = 2 kWh, b: 10 kWh at 60 % = 6 kWh -> plant 8 kWh of 15 kWh.
PLANT_START_KWH = 8.0
PLANT_START_SOC = 100.0 * PLANT_START_KWH / 15.0


def _battery(ess_id: str, capacity_kwh: float, power_kw: float) -> dict:
    return {
        "id": ess_id,
        "label": ess_id,
        "battery_capacity_kwh": capacity_kwh,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_charge_power_kw": power_kw,
        "max_discharge_power_kw": power_kw,
        "max_power_kw": power_kw,
        "efficiency": 0.97,
        "standby_power_kw": 0.0,
        "control": "full",
        "battery_wear": {"enabled": False},
    }


def _batteries() -> list[dict]:
    return [_battery("a", 5.0, 2.5), _battery("b", 10.0, 5.0)]


def _capacity_by_id() -> dict[str, float]:
    return {b["id"]: b["battery_capacity_kwh"] for b in _batteries()}


def _expensive_night(slots: int, *, cheap_first: int = 0) -> list[dict]:
    """No PV, steady load: without an anchor the MILP empties every battery."""
    return [
        {
            "hour": 20 + t // 4,
            "expected_p_pv": 0.0,
            "expected_p_act": 2.0,
            "k_act": 5.0 if t < cheap_first else 40.0,
            "k_push_act": 0.0,
        }
        for t in range(slots)
    ]


def _plant_kwh(slot: dict) -> float:
    by_ess = slot["planned_soc_by_ess"]
    capacity = _capacity_by_id()
    return sum(float(by_ess[eid]) / 100.0 * capacity[eid] for eid in capacity)


def _schedule(matrix: list[dict], **kwargs) -> list[dict]:
    return milp_horizon_schedule(
        matrix,
        current_soc=START_SOC_BY_ID["a"],
        battery_params=_batteries(),
        k_push=0.0,
        verbose=False,
        consumers=[],
        current_soc_by_id=dict(START_SOC_BY_ID),
        **kwargs,
    )


def test_without_anchor_both_batteries_are_emptied():
    schedule = _schedule(_expensive_night(24))
    assert _plant_kwh(schedule[-1]) == pytest.approx(1.5, abs=1e-2)


def test_terminal_soc_binds_the_plant_energy():
    schedule = _schedule(_expensive_night(24), terminal_soc_percent=PLANT_START_SOC)
    assert _plant_kwh(schedule[-1]) == pytest.approx(PLANT_START_KWH, abs=1e-2)


def test_soc_hold_binds_the_plant_energy():
    hold_percent = 70.0
    schedule = _schedule(
        _expensive_night(8, cheap_first=4), soc_hold_index=3, soc_hold_percent=hold_percent
    )
    assert _plant_kwh(schedule[3]) == pytest.approx(hold_percent / 100.0 * 15.0, abs=1e-2)


def test_simulation_passes_the_plant_soc_as_terminal_target(monkeypatch):
    seen: list[float | None] = []

    def _spy(*args, **kwargs):
        seen.append(kwargs.get("terminal_soc_percent"))
        return milp_horizon_schedule(*args, **kwargs)

    monkeypatch.setattr(simulation, "milp_horizon_schedule", _spy)
    matrix = _expensive_night(4)
    simulation.simulate_horizon(
        matrix,
        START_SOC_BY_ID["a"],
        battery_params=_batteries(),
        k_push=0.0,
        verbose=False,
        commit_hours=len(matrix),
        flexible_consumers=[],
        current_soc_by_id=dict(START_SOC_BY_ID),
    )
    assert seen
    assert seen[0] == pytest.approx(PLANT_START_SOC)
