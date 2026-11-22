"""The house profile preview models an EV with the power of its wallbox pair.

Bug: the form stores no ``nominal_power_kw`` on an EV (data model 6: the power follows from
the charge currents and the wallbox). The preview consumers went into the charts
("Gesamt-Lastverhalten") as they were, so ``ev_hourly_kw_for_day`` spread the daily charge
with 0 kW: the EV's series was 0 all year while the Grundlast preview still took its
~3000 kWh/a out of the annual consumption.
"""
from __future__ import annotations

from datetime import date

import pytest

from house_config.ev_profile import ev_daily_kwh, ev_hourly_kw_for_day
from ui import house_config_profile_form as form

WALLBOX = {
    "id": "wb_garage",
    "label": "Wallbox Garage",
    "voltage_v": 220.0,
    "phases": 1,
    "min_current_a": 6.0,
    "max_current_a": 16.0,
    "ehal_bindings": {},
}


def _form_ev(**overrides) -> dict:
    """EV as ``_render_consumer_form`` returns it: currents and wallbox, no power."""
    item = {
        "id": "e_auto",
        "label": "smart",
        "type": "ev",
        "phases": 1,
        "min_current_a": 6.0,
        "max_current_a": 16.0,
        "wallbox_assignment": {"mode": "fixed", "wallbox_id": "wb_garage"},
        "battery_capacity_kwh": 16.0,
        "min_on_quarterhours": 1,
        "charging_schedule": {
            "target_soc_percent": 100.0,
            "charging_efficiency": 0.96,
            "weekday": {
                "car_available_from_hour": 20,
                "ready_by_hour": 7,
                "daily_rest_soc": 40.0,
            },
        },
    }
    item.update(overrides)
    return item


@pytest.fixture
def wallboxes(monkeypatch):
    monkeypatch.setattr(
        "ui.house_config_wallbox_io.wallboxes_map", lambda: {WALLBOX["id"]: dict(WALLBOX)}
    )


def test_preview_ev_carries_the_pair_power_and_charges(wallboxes):
    form_item = _form_ev()
    (ev,) = form._preview_consumers([form_item], heating={"heating_enabled": True})

    assert ev["nominal_power_kw"] == pytest.approx(3.52)  # 16 A x 220 V x 1 phase
    assert ev["min_power_kw"] == pytest.approx(1.32)
    monday = date(2026, 11, 23)
    hourly = ev_hourly_kw_for_day(ev, monday)
    assert sum(hourly) == pytest.approx(ev_daily_kwh(ev, monday))
    assert sum(hourly) > 0
    assert "nominal_power_kw" not in form_item  # the saved form item stays without power


def test_preview_ev_without_a_usable_wallbox_fails_loud(wallboxes):
    missing = _form_ev(wallbox_assignment={"mode": "fixed", "wallbox_id": "gone"})
    with pytest.raises(ValueError, match="gone"):
        form._preview_consumers([missing], heating={"heating_enabled": True})
