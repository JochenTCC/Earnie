"""MILP: pv_follow (PV-Überschuss) vs. feste Leistung."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer.consumer_power import loxone_control_outputs
from optimizer.milp import milp_optimizer


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "efficiency": 0.95,
        "end_soc_equals_start": False,
    }


def _eauto_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "min_on_quarterhours": 1,
        "loxone_outputs": {
            "power_setpoint_name": "Ernie_EAuto_Ziel_kW",
            "pv_follow_name": "Ernie_EAuto_pv_follow",
        },
    }


class TestMilpPvFollow:
    def test_prefers_pv_follow_in_sunny_hour(self):
        matrix = [
            {"hour": 0, "expected_p_pv": 4.0, "expected_p_act": 0.5, "k_act": 8.0},
        ]
        _, _, _, powers, pv_follow, _ = milp_optimizer(
            matrix,
            current_hour=0,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[_eauto_consumer()],
            consumer_remaining_kwh={"eauto": 3.5},
            charging_contexts={},
            flex_indices=[0],
        )
        assert powers["eauto"] == pytest.approx(3.5, abs=0.05)
        assert pv_follow["eauto"] == 1

    def test_loxone_outputs_from_pv_follow_plan(self):
        setpoint, flag = loxone_control_outputs(_eauto_consumer(), 3.5, 1)
        assert setpoint == 3.5
        assert flag == 1

    def test_loxone_outputs_from_fixed_plan(self):
        setpoint, flag = loxone_control_outputs(_eauto_consumer(), 2.2, 0)
        assert setpoint == 2.2
        assert flag == 0
