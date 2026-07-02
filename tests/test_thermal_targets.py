"""Tests für thermische Observability (Phase 0)."""
from __future__ import annotations

from unittest.mock import patch

from optimizer.thermal_targets import build_thermal_observability


def _swimspa_consumer() -> dict:
    return {
        "id": "swimspa",
        "name": "SwimSpa",
        "nominal_power_kw": 2.8,
        "thermal_control": {
            "enabled": True,
            "mode": "active",
            "setpoint_c": 36.5,
            "tolerance_c": 1.0,
            "water_volume_liters": 6000,
            "heat_loss_kw_per_k": 0.01,
            "heating_efficiency": 0.95,
            "heating_power_threshold_kw": 2.0,
            "actual_temp_step_c": 0.5,
            "history_logs": {},
            "loxone": {},
        },
    }


@patch("optimizer.thermal_targets.get_outdoor_forecast_with_fallback")
@patch("integrations.loxone_client.fetch_thermal_readings")
def test_build_thermal_observability_compare(mock_readings, mock_forecast):
    mock_readings.return_value = {
        "actual_c": 36.0,
        "setpoint_c": 36.5,
        "ambient_c": 10.0,
        "tolerance_c": 1.0,
        "missing_signals": [],
    }
    mock_forecast.return_value = ([10.0] * 24, "open_meteo")

    snapshot = build_thermal_observability(
        _swimspa_consumer(),
        baseline_target_kwh=8.0,
        horizon=24,
    )

    assert snapshot["consumer_id"] == "swimspa"
    assert snapshot["mode"] == "active"
    assert snapshot["active_target_kwh"] == snapshot["thermal_target_kwh"]
    assert snapshot["baseline_target_kwh"] == 8.0
    assert snapshot["delta_kwh"] == round(snapshot["thermal_target_kwh"] - 8.0, 3)
