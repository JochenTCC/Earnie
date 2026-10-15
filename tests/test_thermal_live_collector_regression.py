"""Regression: Live heat storage must apply collector heat when solar is omitted.

Bugfix (2026-10-14 / verified 2026-10-15): Live callers never passed
``solar_forecast_kw``, so the planner defaulted to zeros and the store never
collected via the solar thermal collector. ``plan_live_store_for_thermal_consumer``
must auto-resolve collector yield when the arg is ``None``.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from optimizer.thermal_live_store import (
    HeatStorageReadings,
    plan_live_store_for_thermal_consumer,
)

_SETPOINT_C = 47.0
_HORIZON = 6
# Sunny midday-ish collector heat into the store (kW_th ≈ kWh/h).
_SUNNY_MIDDAY_KW = [0.0, 0.5, 2.5, 3.0, 2.8, 1.5]


def _consumer() -> dict:
    return {
        "id": "wp",
        "type": "thermal_annual",
        "nominal_power_kw": 1.9,
        "thermal": {
            "living_area_m2": 0.0,
            "persons": 1,
            "solar_thermal_area_m2": 10.3,
            "solar_thermal_tilt_deg": 18.0,
            "solar_thermal_azimuth_deg": 28.0,
            "heat_storage": {
                "volume_liters": 887.0,
                "heat_loss_kw_per_k": 0.005,
                "setpoint_c": _SETPOINT_C,
                "tolerance_c": 5.0,
            },
        },
    }


_PROFILE = {"latitude": 47.4, "longitude": 9.7}


@patch("optimizer.thermal_live_store.resolve_heat_storage_readings")
def test_live_store_rises_above_setpoint_when_solar_omitted(
    mock_readings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """solar_forecast_kw=None must still heat the store on a sunny midday profile."""
    mock_readings.return_value = HeatStorageReadings(
        temp_eq_c=_SETPOINT_C,
        temp_low_c=None,
        used_measured_eq=True,
        used_measured_low=False,
    )
    monkeypatch.setattr(
        "optimizer.thermal_live_store.resolve_live_collector_solar_kw",
        lambda *_a, **_k: (list(_SUNNY_MIDDAY_KW), "open_meteo"),
    )

    with_solar = plan_live_store_for_thermal_consumer(
        _consumer(),
        house_profile=_PROFILE,
        ambient_forecast_c=[18.0] * _HORIZON,
        solar_forecast_kw=None,
    )
    without_solar = plan_live_store_for_thermal_consumer(
        _consumer(),
        house_profile=_PROFILE,
        ambient_forecast_c=[18.0] * _HORIZON,
        solar_forecast_kw=[0.0] * _HORIZON,
    )

    assert with_solar is not None
    assert without_solar is not None
    assert max(with_solar.store_temp_c) > _SETPOINT_C
    assert max(without_solar.store_temp_c) <= _SETPOINT_C + 0.05
    assert max(with_solar.store_temp_c) > max(without_solar.store_temp_c)
