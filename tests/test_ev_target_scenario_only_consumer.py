"""SE: an EV that only the scenario's house profile has gets its charging target.

``historical_charging_context`` looks up the consumer's horizon target. Without the consumer
in the call, the helper fell back to the Live profile's consumers: a second EV of a scenario
on another house profile (multi-EV) got target 0 and never charged.
"""
from __future__ import annotations

from datetime import date, datetime

from optimizer.charging_context import historical_charging_context

SECOND_EV = {
    "id": "zweitauto",
    "type": "ev",
    "nominal_power_kw": 3.5,
    "min_power_kw": 1.4,
    "min_on_quarterhours": 1,
    "daily_target_kwh": 0.0,
    "daily_target_source": "config",
    "charging_schedule": {
        "enabled": True,
        "weekday": {"car_available_from_hour": 17, "ready_by_hour": 6},
        "weekend": {"car_available_from_hour": 17, "ready_by_hour": 10},
    },
}


def test_scenario_only_ev_gets_its_target(monkeypatch) -> None:
    # Live knows only another EV.
    monkeypatch.setattr(
        "config.get_flexible_consumers",
        lambda optimizer_only=False, **_kw: [{**SECOND_EV, "id": "e_auto"}],
    )
    matrix = [
        {
            "hour": h,
            "date": date(2026, 3, 2),
            "slot_datetime": datetime(2026, 3, 2, h, 0),
            "consumption_mode": "profile_spec",
        }
        for h in range(24)
    ]
    context = historical_charging_context(
        SECOND_EV,
        matrix,
        {"e_auto": 10.0, "zweitauto": 22.375},
        datetime(2026, 3, 2, 0, 0),
        realtime=False,
    )
    assert context["active"] is True
    assert context["target_kwh"] == 22.375
