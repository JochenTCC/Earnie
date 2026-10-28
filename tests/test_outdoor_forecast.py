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


VIENNA = "Europe/Vienna"


def _utc_payload(first_utc: str, values: list[float]) -> dict:
    first = datetime.fromisoformat(first_utc)
    return {
        "hourly": {
            "time": [
                (first + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
                for i in range(len(values))
            ],
            of.HOURLY_TEMP_VAR: values,
        }
    }


def test_fetch_requests_utc_with_one_past_day_and_one_extra_forecast_day():
    seen: dict = {}

    def _payload(_url, params):
        seen.update(params)
        return _utc_payload("2026-10-24T00:00", [1.0, 2.0])

    with patch.object(of, "_open_meteo_payload", _payload), patch.object(
        of.config, "get_planning_timezone", return_value=VIENNA
    ):
        of._fetch_open_meteo_hourly_vars(
            47.4, 9.7, forecast_days=2, hourly_vars=(of.HOURLY_TEMP_VAR,)
        )

    # A zone name would make Open-Meteo apply ONE fixed UTC offset to the whole response.
    assert seen["timezone"] == "UTC"
    # The first local hours of a day belong to the previous UTC day, the last ones to the
    # same UTC day: one past day and one extra forecast day keep the local range covered.
    assert seen["past_days"] == 1
    assert seen["forecast_days"] == 3


def test_forecast_days_with_utc_window_stay_within_the_api_maximum():
    assert of.utc_forecast_params(16)["forecast_days"] == 16


def test_utc_stamps_become_planning_wall_clock_per_timestamp_over_the_autumn_change():
    # 2026-10-25: CEST -> CET at 03:00 local; 00:00 UTC and 01:00 UTC are both 02:00 local.
    payload = _utc_payload("2026-10-24T21:00", [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    parsed = of._parse_open_meteo_hourly(
        payload, (of.HOURLY_TEMP_VAR,), timezone=VIENNA
    )[of.HOURLY_TEMP_VAR]

    assert parsed == [
        (datetime(2026, 10, 24, 23), 0.0),
        (datetime(2026, 10, 25, 0), 1.0),
        (datetime(2026, 10, 25, 1), 2.0),
        (datetime(2026, 10, 25, 2), 3.5),  # repeated hour: mean of both
        (datetime(2026, 10, 25, 3), 5.0),
    ]


def test_utc_stamps_become_planning_wall_clock_per_timestamp_over_the_spring_change():
    # 2026-03-29: CET -> CEST at 02:00 local; 01:00 UTC is already 03:00 local.
    payload = _utc_payload("2026-03-28T23:00", [0.0, 1.0, 2.0])
    parsed = of._parse_open_meteo_hourly(
        payload, (of.HOURLY_TEMP_VAR,), timezone=VIENNA
    )[of.HOURLY_TEMP_VAR]

    assert parsed == [
        (datetime(2026, 3, 29, 0), 0.0),
        (datetime(2026, 3, 29, 1), 1.0),
        (datetime(2026, 3, 29, 3), 2.0),
    ]


def test_map_to_horizon_skipped_spring_hour_takes_the_next_existing_hour():
    hourly = [
        (datetime(2026, 3, 29, 0), 0.0),
        (datetime(2026, 3, 29, 1), 1.0),
        (datetime(2026, 3, 29, 3), 2.0),
        (datetime(2026, 3, 29, 4), 3.0),
    ]
    with patch.object(of.config, "get_planning_timezone", return_value=VIENNA):
        vector = of._map_to_horizon(hourly, datetime(2026, 3, 29, 1), 4)

    assert vector == [1.0, 2.0, 2.0, 3.0]


def test_map_to_horizon_still_rejects_a_genuinely_missing_hour():
    hourly = [(datetime(2026, 7, 6, 10), 1.0), (datetime(2026, 7, 6, 12), 2.0)]
    with patch.object(of.config, "get_planning_timezone", return_value=VIENNA):
        with pytest.raises(ValueError, match="keine Temperatur"):
            of._map_to_horizon(hourly, datetime(2026, 7, 6, 10), 3)
