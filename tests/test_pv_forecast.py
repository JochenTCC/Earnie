"""Tests für forecast.solar Retry-At und Cache in data/pv_forecast."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from data import pv_forecast as pf


@pytest.fixture(autouse=True)
def reset_pv_forecast_state():
    pf._LAST_API_CALL = None
    pf._CACHED_HOURLY_WATTS = None
    pf._RATE_LIMIT_RETRY_AT = None
    pf._LAST_FETCH_SOURCE = "api"
    pf._USING_SYNTHETIC_FALLBACK = False
    yield


def _config_get_side_effect(key, *, cast=None):
    values = {
        "LATITUDE": 51.0,
        "LONGITUDE": 10.0,
        "PV_TILT": 35.0,
        "PV_AZIMUTH": 0.0,
        "PV_KWP": 6.0,
    }
    value = values[key]
    return cast(value) if cast else value


def _target_hours() -> list[datetime]:
    base = datetime(2026, 7, 15, 10, 0, 0)
    return [base + timedelta(hours=i) for i in range(3)]


def _ok_response(watts: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "result": {
            "watts": watts
            or {
                "2026-07-15 10:00:00": 1000,
                "2026-07-15 11:00:00": 2000,
                "2026-07-15 12:00:00": 3000,
            }
        }
    }
    return response


def _429_response(*, header: str | None = None, body: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = 429
    response.headers = {"X-Ratelimit-Retry-At": header} if header else {}
    response.json.return_value = body or {"message": {"ratelimit": {}}}
    return response


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_429_header_sets_retry_at_and_blocks_second_http(
    get_mock, _config_mock, _timeout_mock
):
    retry_at = datetime.now() + timedelta(hours=1)
    get_mock.return_value = _429_response(header=retry_at.isoformat())

    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    status = pf.get_api_status()
    assert status["retry_at"] == retry_at.isoformat()
    assert status["source"] == "rate_limited"
    assert get_mock.call_count == 1

    get_mock.reset_mock()
    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert get_mock.call_count == 0
    assert pf.get_api_status()["source"] == "rate_limited"


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_429_json_body_sets_retry_at(get_mock, _config_mock, _timeout_mock):
    retry_at = datetime(2026, 7, 15, 12, 30, 0)
    get_mock.return_value = _429_response(
        body={
            "message": {
                "ratelimit": {
                    "retry-at": retry_at.isoformat(),
                }
            }
        }
    )

    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert pf.get_api_status()["retry_at"] == retry_at.isoformat()


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_200_after_429_clears_retry_at_and_updates_last_api_call(
    get_mock, _config_mock, _timeout_mock
):
    pf._RATE_LIMIT_RETRY_AT = datetime.now() - timedelta(minutes=1)
    get_mock.return_value = _ok_response()

    before = datetime.now()
    result = pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert pf.get_api_status()["retry_at"] is None
    assert pf.get_api_status()["source"] == "api"
    assert pf._LAST_API_CALL is not None
    assert pf._LAST_API_CALL >= before
    assert result == [1.0, 2.0, 3.0]


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_429_does_not_update_last_api_call(get_mock, _config_mock, _timeout_mock):
    get_mock.return_value = _429_response(header=(datetime.now() + timedelta(hours=1)).isoformat())

    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert pf._LAST_API_CALL is None


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_15_min_cache_skips_second_http(get_mock, _config_mock, _timeout_mock):
    get_mock.return_value = _ok_response()
    pf.get_hourly_pv_forecast_for_hours(_target_hours())
    assert get_mock.call_count == 1

    get_mock.reset_mock()
    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert get_mock.call_count == 0
    assert pf.get_api_status()["source"] == "cache"


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_http_error_does_not_update_last_api_call(get_mock, _config_mock, _timeout_mock):
    response = MagicMock()
    response.status_code = 500
    response.raise_for_status.side_effect = requests.HTTPError("500", response=response)
    get_mock.return_value = response

    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert pf._LAST_API_CALL is None
    assert pf.get_api_status()["using_synthetic_fallback"] is True


def test_parse_retry_at_prefers_header():
    response = MagicMock()
    response.headers = {"X-Ratelimit-Retry-At": "2026-07-15T14:00:00+02:00"}
    response.json.return_value = {
        "message": {"ratelimit": {"retry-at": "2026-07-15T15:00:00+02:00"}}
    }

    parsed = pf._parse_retry_at(response)

    assert parsed == datetime.fromisoformat("2026-07-15T14:00:00+02:00")
