"""Open-Meteo-Außentemperatur-Prognose."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from data import outdoor_forecast as of


def test_required_forecast_days_short_horizon_same_day():
    start = datetime(2026, 7, 6, 14, 0, 0)
    with patch.object(of, "datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 6, 14, 0, 0)
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        assert of._required_forecast_days(start, 24) == 2


def test_required_forecast_days_sunset_horizon_spans_third_day():
    start = datetime(2026, 7, 6, 14, 0, 0)
    with patch.object(of, "datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 6, 14, 0, 0)
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        assert of._required_forecast_days(start, 40) == 3


def test_required_forecast_days_capped_at_api_maximum():
    start = datetime(2026, 7, 6, 12, 0, 0)
    with patch.object(of, "datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 6, 12, 0, 0)
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        assert of._required_forecast_days(start, 24 * 20) == 16


def _hourly_payload(start: datetime, hours: int) -> list[tuple[datetime, float]]:
    return [
        (start + timedelta(hours=offset), 20.0 + offset * 0.1)
        for offset in range(hours)
    ]


def test_map_to_horizon_40h_with_three_day_fetch():
    start = datetime(2026, 7, 6, 14, 0, 0)
    hourly = _hourly_payload(datetime(2026, 7, 6, 0, 0, 0), 72)

    vector = of._map_to_horizon(hourly, start, 40)

    assert len(vector) == 40
    assert vector[-1] == round(20.0 + 53 * 0.1, 3)


def test_get_hourly_outdoor_forecast_requests_enough_forecast_days():
    of._CACHE.clear()
    start = datetime(2026, 7, 6, 14, 0, 0)
    hourly = _hourly_payload(datetime(2026, 7, 6, 0, 0, 0), 72)

    with patch.object(of, "datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 6, 14, 0, 0)
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        with patch.object(
            of,
            "_fetch_open_meteo_hourly",
            return_value=hourly,
        ) as fetch_mock:
            vector = of.get_hourly_outdoor_forecast_c(
                horizon=40,
                latitude=47.4,
                longitude=9.7,
                start=start,
            )

    fetch_mock.assert_called_once_with(47.4, 9.7, forecast_days=3)
    assert len(vector) == 40


def test_cache_separates_forecast_day_ranges():
    of._CACHE.clear()
    start = datetime(2026, 7, 6, 14, 0, 0)
    hourly_short = _hourly_payload(datetime(2026, 7, 6, 0, 0, 0), 48)
    hourly_long = _hourly_payload(datetime(2026, 7, 6, 0, 0, 0), 72)

    with patch.object(of, "datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 6, 14, 0, 0)
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        with patch.object(
            of,
            "_fetch_open_meteo_hourly",
            side_effect=[hourly_short, hourly_long],
        ) as fetch_mock:
            of.get_hourly_outdoor_forecast_c(
                horizon=24,
                latitude=47.4,
                longitude=9.7,
                start=start,
            )
            of.get_hourly_outdoor_forecast_c(
                horizon=40,
                latitude=47.4,
                longitude=9.7,
                start=start,
            )

    assert fetch_mock.call_count == 2
    assert fetch_mock.call_args_list[0].kwargs["forecast_days"] == 2
    assert fetch_mock.call_args_list[1].kwargs["forecast_days"] == 3
