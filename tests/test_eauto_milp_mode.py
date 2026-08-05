"""Tests für E-Auto MILP Modus A/B (Live) und Modus B (Backtesting)."""
from __future__ import annotations

import os

import pulp
import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from optimizer.eauto_milp import (
    eauto_modus_b_uses_milp,
    eauto_preset_charge_kw,
    eauto_preset_power_now,
    ev_in_modus_b,
    ev_modus_a_active,
    is_logged_day_matrix,
    milp_binary_charge_kw,
    milp_uses_power_setpoint,
    validate_eauto_milp_params,
)
from optimizer.milp import _build_milp_model, milp_horizon_schedule, milp_optimizer


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
    }


def _eauto_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "min_on_quarterhours": 1,
        "ehal_bindings": {"set_evcs_max_current": "Earnie_EAuto_Soll_A"},
        "charging_schedule": {
            "enabled": True,
            "milp": {
                "live_modus_a_min_remaining_kwh": 2.8,
                "tie_break_on_epsilon": 0.001,
                "tie_break_time_epsilon": 0.0001,
            },
        },
    }


def _ev_consumer_canonical() -> dict:
    return {
        "id": "ev",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "min_on_quarterhours": 1,
        "ehal_bindings": {"set_evcs_max_current": "Earnie_EAuto_Soll_A"},
        "charging_schedule": {
            "enabled": True,
            "milp": {
                "live_modus_a_min_remaining_kwh": 2.8,
                "tie_break_on_epsilon": 0.001,
                "tie_break_time_epsilon": 0.0001,
            },
        },
    }


def _eauto_milp_params() -> dict[str, float]:
    return {
        "live_modus_a_min_remaining_kwh": 2.8,
        "tie_break_on_epsilon": 0.001,
        "tie_break_time_epsilon": 0.0001,
    }


class TestEautoMilpConfig:
    def test_validate_requires_all_keys(self):
        with pytest.raises(ValueError, match="live_modus_a_min_remaining_kwh"):
            validate_eauto_milp_params({})

    def test_validate_rejects_non_positive_threshold(self):
        with pytest.raises(ValueError, match="live_modus_a_min_remaining_kwh"):
            validate_eauto_milp_params({
                "live_modus_a_min_remaining_kwh": 0.0,
                "tie_break_on_epsilon": 0.001,
                "tie_break_time_epsilon": 0.0001,
            })


class TestEautoMilpModeSelection:
    def test_logged_day_disables_power_setpoint_in_milp(self):
        consumer = _eauto_consumer()
        params = _eauto_milp_params()
        assert milp_uses_power_setpoint(
            consumer, _matrix(logged_day=True), 7.0, params
        ) is False
        assert milp_uses_power_setpoint(
            consumer, _matrix(logged_day=False), 7.0, params
        ) is True

    def test_live_modus_b_below_threshold(self):
        consumer = _eauto_consumer()
        params = _eauto_milp_params()
        matrix = _matrix()
        assert not ev_modus_a_active(consumer, matrix, 2.0, params)
        assert ev_in_modus_b(consumer, matrix, 2.0, params)

    def test_live_modus_a_above_threshold(self):
        consumer = _eauto_consumer()
        params = _eauto_milp_params()
        matrix = _matrix()
        assert ev_modus_a_active(consumer, matrix, 3.0, params)
        assert not ev_in_modus_b(consumer, matrix, 3.0, params)

    def test_binary_charge_kw_is_p_nom_in_modus_b(self):
        consumer = _eauto_consumer()
        params = _eauto_milp_params()
        assert milp_binary_charge_kw(
            consumer, _matrix(logged_day=True), 7.0, params
        ) == 3.5

    def test_logged_day_model_has_no_continuous_eauto_power_vars(self):
        params = _eauto_milp_params()
        model = _build_milp_model(
            _matrix(4, logged_day=True),
            4,
            _battery_params(),
            50.0,
            [_eauto_consumer()],
            0.0,
            {"eauto": 7.0},
            {"eauto": params},
        )
        assert is_logged_day_matrix(_matrix(logged_day=True))
        assert "eauto" not in model.consumer_p
        assert model.consumer_milp_charge_kw["eauto"] == 3.5
        assert len(model.consumer_on["eauto"]) == 4

    def test_live_modus_a_model_has_continuous_power_vars(self):
        params = _eauto_milp_params()
        model = _build_milp_model(
            _matrix(4, logged_day=False),
            4,
            _battery_params(),
            50.0,
            [_eauto_consumer()],
            0.0,
            {"eauto": 7.0},
            {"eauto": params},
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
    def test_modus_b_milp_when_remaining_gt_p_nom(self):
        consumer = _eauto_consumer()
        matrix = _matrix(6, logged_day=True)
        params = _eauto_milp_params()
        assert eauto_modus_b_uses_milp(consumer, matrix, 7.0, params)
        assert not eauto_modus_b_uses_milp(consumer, matrix, 3.5, params)

    def test_preset_charge_kw_clamps_to_p_min(self):
        consumer = _eauto_consumer()
        assert eauto_preset_charge_kw(consumer, 0.3) == 1.4
        assert eauto_preset_charge_kw(consumer, 2.0) == 2.0
        assert eauto_preset_charge_kw(consumer, 3.5) == 3.5

    def test_preset_charges_at_cheapest_hour_only(self):
        consumer = _eauto_consumer()
        matrix = _matrix(6, logged_day=True)
        params = _eauto_milp_params()
        schedule = list(range(6))
        assert eauto_preset_power_now(
            matrix, consumer, 1.0, schedule, None, params
        ) == 1.4
        assert eauto_preset_power_now(
            matrix, consumer, 1.0, schedule[3:], None, params
        ) == 0.0

    def test_preset_charges_when_deadline_slots_exhausted(self):
        """Tail after partial MILP: preset must deliver when only one slot remains."""
        from datetime import datetime

        consumer = _ev_consumer_canonical()
        consumer["nominal_power_kw"] = 11.0
        deadline = datetime(2026, 5, 14, 7, 0)
        matrix = [
            {
                "slot_datetime": datetime(2026, 5, 14, 6, 0),
                "hour": 6,
                "expected_p_pv": 0.0,
                "expected_p_act": 0.5,
                "k_act": 20.0,
                "consumption_mode": "logged_day",
            }
        ]
        params = _eauto_milp_params()
        ctx = {
            "active": True,
            "deadline": deadline,
            "use_time_window": True,
            "config_day_schedule": {
                "car_available_from_hour": 18,
                "ready_by_hour": 7,
            },
        }
        power = eauto_preset_power_now(
            matrix, consumer, 5.842, [0], ctx, params
        )
        assert power == pytest.approx(5.842, abs=0.01)

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

    def test_logged_day_open_loop_places_preset_at_cheapest_not_t0(self):
        """SE sunrise open-loop: small EV target must land on cheapest eligible hour."""
        from datetime import datetime, timedelta

        start = datetime(2025, 2, 3, 7, 0)
        matrix = []
        for index in range(24):
            slot = start + timedelta(hours=index)
            price = 5.0 if slot.hour in (2, 3, 4) else 40.0
            matrix.append(
                {
                    "hour": slot.hour,
                    "date": slot.date(),
                    "slot_datetime": slot,
                    "charging_anchor": datetime(2025, 2, 4, 7),
                    "consumption_mode": "profile_spec",
                    "expected_p_pv": 0.0,
                    "expected_p_act": 0.5,
                    "k_act": price,
                }
            )
        consumer = _eauto_consumer()
        ctx = {
            "active": True,
            "deadline": datetime(2025, 2, 4, 7),
            "target_kwh": 1.44,
            "use_time_window": True,
            "config_day_schedule": {
                "car_available_from_hour": 18,
                "ready_by_hour": 7,
            },
        }
        schedule = milp_horizon_schedule(
            matrix,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[consumer],
            consumer_remaining_kwh={"eauto": 1.44},
            charging_contexts={"eauto": ctx},
        )
        powers = [float(slot["consumer_powers"].get("eauto", 0.0)) for slot in schedule]
        assert sum(powers) == pytest.approx(1.44, abs=0.01)
        assert powers[0] == 0.0
        # hour 2 is first cheapest eligible night slot (index 19 from 07:00 start)
        assert powers[19] == pytest.approx(1.44, abs=0.01)

    def test_live_small_target_uses_preset(self):
        _, _, _, powers, _, _, _ = milp_optimizer(
            _matrix(6, logged_day=False),
            current_hour=0,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[_eauto_consumer()],
            consumer_remaining_kwh={"eauto": 2.0},
            charging_contexts={},
        )
        assert powers["eauto"] == 2.0

    def test_live_large_target_uses_modus_a(self):
        _, _, _, powers, _, _, _ = milp_optimizer(
            _matrix(6, logged_day=False),
            current_hour=0,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[_eauto_consumer()],
            consumer_remaining_kwh={"eauto": 7.0},
            charging_contexts={},
        )
        power = powers["eauto"]
        assert power == 0.0 or 1.4 <= power <= 3.5

    def test_preset_excluded_from_milp_variables(self):
        model = _build_milp_model(
            _matrix(4, logged_day=True),
            4,
            _battery_params(),
            50.0,
            [],
            1.4,
            {"eauto": 1.0},
            {"eauto": _eauto_milp_params()},
        )
        assert "eauto" not in model.consumer_on
        model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
        assert pulp.LpStatus[model.prob.status] == "Optimal"


class TestEautoTieBreak:
    def test_prefers_earlier_hour_at_equal_prices(self):
        matrix = []
        for h in range(6):
            matrix.append({
                "hour": h,
                "expected_p_pv": 0.0,
                "expected_p_act": 0.5,
                "k_act": 10.0,
                "consumption_mode": "logged_day",
            })
        params = _eauto_milp_params()
        model = _build_milp_model(
            matrix,
            6,
            _battery_params(),
            50.0,
            [_eauto_consumer()],
            0.0,
            {"eauto": 7.0},
            {"eauto": params},
        )
        from optimizer.milp import _add_consumer_delivery_constraints, _add_milp_objective

        _add_milp_objective(model, matrix, 3.5, {"eauto": params}, wear_cent_per_kwh=0.0)
        _add_consumer_delivery_constraints(
            model,
            matrix,
            {"eauto": 7.0},
            list(range(6)),
            {},
            False,
        )
        model.prob.solve(pulp.PULP_CBC_CMD(msg=False))
        assert pulp.LpStatus[model.prob.status] == "Optimal"
        on = model.consumer_on["eauto"]
        assert on[0].varValue is not None and on[0].varValue > 0.5
