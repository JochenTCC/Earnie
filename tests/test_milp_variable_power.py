"""MILP mit variablem kW-Sollwert für flexible Verbraucher."""
from __future__ import annotations

import os

import pulp
import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from optimizer.milp import _build_milp_model, milp_horizon_schedule


def _matrix(hours: int = 6) -> list[dict]:
    rows = []
    for h in range(hours):
        rows.append({
            "hour": h,
            "expected_p_pv": 2.0 if h < 3 else 0.0,
            "expected_p_act": 0.5,
            "k_act": 10.0 if h < 3 else 30.0,
        })
    return rows


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "efficiency": 0.95,
    }


def _eauto_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "min_on_quarterhours": 1,
        "ehal_bindings": {"set_evcs_max_current": "Earnie_EAuto_Soll_A"},
    }


def test_partial_power_when_target_below_max():
    """Partial continuous setpoint (~2 kW) somewhere in the horizon (solver-agnostic)."""
    consumers = [_eauto_consumer()]
    matrix = _matrix(6)
    schedule = milp_horizon_schedule(
        matrix,
        current_soc=50.0,
        battery_params=_battery_params(),
        k_push=3.5,
        verbose=False,
        consumers=consumers,
        consumer_remaining_kwh={"eauto": 2.0},
        charging_contexts={},
    )
    powers = [slot["consumer_powers"].get("eauto", 0.0) for slot in schedule]
    assert any(0.0 < p <= 3.5 for p in powers)
    assert any(abs(p - 2.0) <= 0.05 for p in powers)
    assert sum(powers) == pytest.approx(2.0, abs=0.05)


def test_model_has_continuous_power_variables():
    model = _build_milp_model(
        _matrix(4),
        4,
        _battery_params(),
        50.0,
        [_eauto_consumer()],
        0.0,
        {"eauto": 7.0},
        {
            "live_modus_a_min_remaining_kwh": 2.8,
            "tie_break_on_epsilon": 0.001,
            "tie_break_time_epsilon": 0.0001,
        },
    )
    assert "eauto" in model.consumer_p
    assert len(model.consumer_p["eauto"]) == 4
    model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
