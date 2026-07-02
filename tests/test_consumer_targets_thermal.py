"""Tests für daily_target_source=thermal."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from data import consumer_targets


def _swimspa() -> dict:
    return {
        "id": "swimspa",
        "name": "SwimSpa",
        "nominal_power_kw": 2.8,
        "daily_target_kwh": 8.0,
        "daily_target_source": "thermal",
        "thermal_control": {
            "enabled": True,
            "mode": "active",
            "water_volume_liters": 6000,
            "heat_loss_kw_per_k": 0.01,
            "heating_efficiency": 0.95,
            "heating_power_threshold_kw": 2.0,
        },
    }


@patch("optimizer.thermal_targets.resolve_thermal_daily_target_kwh")
def test_resolve_thermal_source_for_today(mock_resolve):
    mock_resolve.return_value = 12.5
    today = date.today()
    result = consumer_targets._resolve_single_consumer_daily_target_kwh(
        _swimspa(),
        today,
        [{"date": today}] * 24,
        {},
    )
    assert result == 12.5
    mock_resolve.assert_called_once()


def test_resolve_thermal_rejects_past_date():
    try:
        consumer_targets._resolve_single_consumer_daily_target_kwh(
            _swimspa(),
            date(2020, 1, 1),
            None,
            {},
        )
        assert False, "ValueError erwartet"
    except ValueError as exc:
        assert "thermal" in str(exc)
