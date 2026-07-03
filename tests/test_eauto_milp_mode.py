"""Tests für E-Auto MILP Modus B (binär) im Backtesting."""
from __future__ import annotations

import os

import pulp
import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer.eauto_milp import (
    eauto_backtesting_uses_milp,
    eauto_preset_charge_kw,
    eauto_preset_power_now,
    is_logged_day_matrix,
    milp_binary_charge_kw,
    milp_uses_power_setpoint,
)
from optimizer.milp import _build_milp_model, milp_optimizer


def _matrix(hours: int = 6, *, logged_day: bool = False) -> list[dict]:
    rows = []
    for h in range(hours):
        row = {
            "hour": h,
            "expected_p_pv": 2.0 if h < 3 else 0.0,
            "expected_p_act": 0.5,
            "k_act": 10.0 if h < 3 else 30.0,
        }
        if logged_day:
            row["consumption_mode"] = "logged_day"
        rows.append(row)
    return rows


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
        "loxone_outputs": {"power_setpoint_name": "Ernie_EAuto_Ziel_kW"},
    }


class TestEautoMilpModeSelection:
    def test_logged_day_disables_power_setpoint_in_milp(self):
        consumer = _eauto_consumer()
        assert milp_uses_power_setpoint(consumer, _matrix(logged_day=True)) is False
        assert milp_uses_power_setpoint(consumer, _matrix(logged_day=False)) is True

    def test_binary_charge_kw_is_p_nom_in_backtesting(self):
        consumer = _eauto_consumer()
        assert milp_binary_charge_kw(consumer, _matrix(logged_day=True)) == 3.5
        assert milp_binary_charge_kw(consumer, _matrix(logged_day=False)) == 3.5

    def test_logged_day_model_has_no_continuous_eauto_power_vars(self):
        model = _build_milp_model(
            _matrix(4, logged_day=True),
            4,
            _battery_params(),
            50.0,
            [_eauto_consumer()],
            0.0,
        )
        assert is_logged_day_matrix(_matrix(logged_day=True))
        assert "eauto" not in model.consumer_p
        assert model.consumer_milp_charge_kw["eauto"] == 3.5
        assert len(model.consumer_on["eauto"]) == 4

    def test_live_model_keeps_continuous_eauto_power_vars(self):
        model = _build_milp_model(
            _matrix(4, logged_day=False),
            4,
            _battery_params(),
            50.0,
            [_eauto_consumer()],
            0.0,
        )
        assert "eauto" in model.consumer_p
        assert len(model.consumer_p["eauto"]) == 4

    def test_logged_day_milp_solves_with_large_eauto_target(self):
        _, _, _, powers, _, _, _ = milp_optimizer(
            _matrix(6, logged_day=True),
            current_hour=0,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[_eauto_consumer()],
            consumer_remaining_kwh={"eauto": 7.0},
            charging_contexts={},
        )
        assert powers["eauto"] in (0.0, 3.5)


class TestEautoBacktestingPreset:
    def test_preset_mode_when_remaining_leq_p_nom(self):
        consumer = _eauto_consumer()
        matrix = _matrix(6, logged_day=True)
        assert not eauto_backtesting_uses_milp(consumer, matrix, 1.0)
        assert eauto_backtesting_uses_milp(consumer, matrix, 3.51)

    def test_preset_charge_kw_clamps_to_p_min(self):
        consumer = _eauto_consumer()
        assert eauto_preset_charge_kw(consumer, 0.3) == 1.4
        assert eauto_preset_charge_kw(consumer, 2.0) == 2.0
        assert eauto_preset_charge_kw(consumer, 3.5) == 3.5

    def test_preset_charges_at_cheapest_hour_only(self):
        consumer = _eauto_consumer()
        matrix = _matrix(6, logged_day=True)
        schedule = list(range(6))
        assert eauto_preset_power_now(matrix, consumer, 1.0, schedule, None) == 1.4
        assert eauto_preset_power_now(matrix, consumer, 1.0, schedule[3:], None) == 0.0

    def test_logged_day_small_target_uses_preset_not_milp(self):
        _, _, _, powers, _, _, _ = milp_optimizer(
            _matrix(6, logged_day=True),
            current_hour=0,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[_eauto_consumer()],
            consumer_remaining_kwh={"eauto": 1.0},
            charging_contexts={},
        )
        assert powers["eauto"] == 1.4

    def test_preset_excluded_from_milp_variables(self):
        model = _build_milp_model(
            _matrix(4, logged_day=True),
            4,
            _battery_params(),
            50.0,
            [],
            1.4,
        )
        assert "eauto" not in model.consumer_on
        model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
        assert pulp.LpStatus[model.prob.status] == "Optimal"
