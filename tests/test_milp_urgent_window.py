"""MILP: optionales Laden vor dem urgent-Fenster vs. Pflicht-Nachholen."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer.milp import milp_optimizer

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
        "loxone_outputs": {"power_setpoint_name": "Ernie_EAuto_Ziel_kW"},
        "charging_schedule": {"enabled": True},
    }


def _plugged_in_matrix() -> tuple[list[dict], datetime]:
    start = datetime(2026, 6, 28, 9, 0)
    deadline = datetime(2026, 6, 29, 7, 45)
    matrix: list[dict] = []
    for i in range(24):
        dt = start + timedelta(hours=i)
        if dt >= deadline:
            break
        if dt.date() == start.date() and 10 <= dt.hour <= 14:
            price = 2.0
            pv = 2.5
        elif dt.date() == deadline.date() and 5 <= dt.hour <= 7:
            price = 16.0
            pv = 0.1
        else:
            price = 12.0
            pv = 0.3
        matrix.append(
            {
                "slot_datetime": dt,
                "hour": dt.hour,
                "date": dt.date(),
                "expected_p_pv": pv,
                "expected_p_act": 0.5,
                "k_act": price,
            }
        )
    return matrix, deadline


class TestMilpUrgentWindow:
    def test_live_may_charge_in_cheap_hours(self):
        """Live-MILP: günstige Stunden vor Deadline, urgent-Observability redundant."""
        matrix, deadline = _plugged_in_matrix()
        _, _, _, _, _, _, obs = milp_optimizer(
            matrix,
            current_hour=0,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[_eauto_consumer()],
            consumer_remaining_kwh={"eauto": 8.0},
            charging_contexts={
                "eauto": {
                    "active": True,
                    "plugged_in": True,
                    "deadline": deadline,
                    "target_kwh": 8.0,
                    "use_time_window": False,
                }
            },
            flex_indices=list(range(len(matrix))),
        )
        assert obs["eauto"]["role"] == "redundant"
        assert obs["eauto"]["planned_pre_urgent_kwh"] >= 6.0
        assert obs["eauto"]["planned_urgent_kwh"] == 0.0

    def test_logged_day_may_charge_in_cheap_hours_without_urgent(self):
        """Backtesting (logged_day): ohne urgent-Nebenbedingung günstige Stunden nutzbar."""
        matrix, deadline = _plugged_in_matrix()
        for row in matrix:
            row["consumption_mode"] = "logged_day"
        _, _, _, _, _, _, obs = milp_optimizer(
            matrix,
            current_hour=0,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[_eauto_consumer()],
            consumer_remaining_kwh={"eauto": 8.0},
            charging_contexts={
                "eauto": {
                    "active": True,
                    "plugged_in": True,
                    "deadline": deadline,
                    "target_kwh": 8.0,
                    "use_time_window": False,
                }
            },
            flex_indices=list(range(len(matrix))),
        )
        assert obs["eauto"]["role"] == "redundant"
        assert obs["eauto"]["planned_pre_urgent_kwh"] >= 6.0
        assert obs["eauto"]["planned_urgent_kwh"] == 0.0

    def test_must_catch_up_in_urgent_if_not_charged_earlier(self):
        deadline = datetime(2026, 6, 29, 7, 45)
        urgent_only = [
            {
                "slot_datetime": datetime(2026, 6, 29, hour, 0),
                "hour": hour,
                "date": datetime(2026, 6, 29).date(),
                "expected_p_pv": 0.1,
                "expected_p_act": 0.5,
                "k_act": 16.0,
            }
            for hour in (6, 7)
        ]
        _, _, _, _, _, _, obs = milp_optimizer(
            urgent_only,
            current_hour=0,
            current_soc=50.0,
            battery_params=_battery_params(),
            k_push=3.5,
            verbose=False,
            consumers=[_eauto_consumer()],
            consumer_remaining_kwh={"eauto": 6.0},
            charging_contexts={
                "eauto": {
                    "active": True,
                    "plugged_in": True,
                    "deadline": deadline,
                    "target_kwh": 6.0,
                    "use_time_window": False,
                }
            },
            flex_indices=list(range(len(urgent_only))),
        )
        assert obs["eauto"]["role"] == "nur_urgent_fenster"
        assert obs["eauto"]["planned_urgent_kwh"] >= 5.5
