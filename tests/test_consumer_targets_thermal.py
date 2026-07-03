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


@patch("data.consumer_targets._historical_target_kwh")
def test_resolve_thermal_uses_historical_for_other_dates(mock_historical):
    mock_historical.return_value = 6.0
    other_day = date(2020, 1, 1)
    result = consumer_targets._resolve_single_consumer_daily_target_kwh(
        _swimspa(),
        other_day,
        None,
        {},
    )
    assert result == 6.0
    mock_historical.assert_called_once()


@patch("config.get_flexible_consumers")
@patch("optimizer.thermal_targets.resolve_thermal_daily_target_kwh")
def test_resolve_consumer_daily_targets_multi_day_matrix(mock_resolve, mock_consumers):
    mock_consumers.return_value = [_swimspa()]
    mock_resolve.return_value = 12.5
    today = date.today()
    tomorrow = date.fromordinal(today.toordinal() + 1)
    matrix = [{"date": today, "expected_flex_kw": {"swimspa": 0.5}}] * 18
    matrix += [{"date": tomorrow, "expected_flex_kw": {"swimspa": 0.4}}] * 6
    with patch("data.consumer_targets._historical_target_kwh", return_value=2.4):
        targets = consumer_targets.resolve_consumer_daily_targets(matrix=matrix)
    assert set(targets.keys()) == {today, tomorrow}
    assert targets[today]["swimspa"] == 12.5
    assert targets[tomorrow]["swimspa"] == 2.4
    mock_resolve.assert_called_once()
