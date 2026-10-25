"""Tests: charge_immediate_name bleibt im Hausprofil-EV (Planning-Bridge) erhalten."""
from __future__ import annotations

from house_config.planning_flex_bridge import planning_ev_to_milp


def _profile_ev() -> dict:
    return {
        "id": "eauto",
        "label": "E-Auto",
        "type": "ev",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "battery_capacity_kwh": 17.0,
        "charging_schedule": {
            "target_soc_percent": 100.0,
            "charging_efficiency": 0.95,
            "weekday": {"car_available_from_hour": 18, "ready_by_hour": 7, "daily_rest_soc": 40.0},
            "weekend": {"car_available_from_hour": 20, "ready_by_hour": 9, "daily_rest_soc": 30.0},
            "loxone": {
                "plugged_in_name": "EAuto_Angeschlossen",
                "charge_immediate_name": "E-Auto_SOFORT_LADEN",
                "charge_immediate_remaining_name": "Ernie_Restzeit_Sofortladen",
                "battery_capacity_kwh_name": "Batteriekapazität_E-Auto",
            },
        },
    }


def test_charge_immediate_name_kept_in_planning_ev():
    ev = planning_ev_to_milp(_profile_ev())
    lox = ev["charging_schedule"]["loxone"]
    assert lox["charge_immediate_name"] == "E-Auto_SOFORT_LADEN"
    assert lox["charge_immediate_remaining_name"] == "Ernie_Restzeit_Sofortladen"
    assert lox["battery_capacity_kwh_name"] == "Batteriekapazität_E-Auto"
