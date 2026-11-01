"""Tests für forecast.solar Retry-At und Cache in data/pv_forecast."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from data import pv_forecast as pf


@pytest.fixture(autouse=True)
def reset_pv_forecast_state(tmp_path, monkeypatch):
    pf._LAST_API_CALL_BY_URL = {}
    pf._CACHED_HOURLY_WATTS_BY_URL = {}
    pf._DISK_CACHE_CHECKED_URLS = set()
    pf._RATE_LIMIT_RETRY_AT = None
    pf._LAST_FETCH_SOURCE = "api"
    pf._SOURCE_BY_SYSTEM = {}
    monkeypatch.setattr(pf, "_disk_cache_path", lambda: str(tmp_path / pf.DISK_CACHE_FILENAME))
    # Legacy single system from PV_* keys (id "pv"); tests with several systems patch this.
    monkeypatch.setattr(pf.config, "get_planning_pv_systems", lambda: [])
    # No real Open-Meteo calls: a dark sky unless a test patches its own irradiance.
    monkeypatch.setattr(
        "data.outdoor_forecast.get_hourly_tilted_irradiance_forecast_wm2",
        lambda **kwargs: [0.0] * kwargs["horizon"],
    )
    yield


def _restart_process() -> None:
    """Drop in-memory state as a daemon restart would (disk cache stays)."""
    pf._LAST_API_CALL_BY_URL = {}
    pf._CACHED_HOURLY_WATTS_BY_URL = {}
    pf._DISK_CACHE_CHECKED_URLS = set()
    pf._RATE_LIMIT_RETRY_AT = None


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


def _age_last_api_calls(age: timedelta) -> None:
    for url in pf._LAST_API_CALL_BY_URL:
        pf._LAST_API_CALL_BY_URL[url] = datetime.now() - age


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
                "2026-07-15 13:00:00": 4000,
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
def test_429_aware_retry_at_does_not_crash_on_naive_now(
    get_mock, _config_mock, _timeout_mock
):
    """forecast.solar often returns offset-aware Retry-At; now() is naive."""
    from datetime import timezone

    retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    get_mock.return_value = _429_response(header=retry_at.isoformat())

    pf.get_hourly_pv_forecast_for_hours(_target_hours())
    # Second call hits _pre_fetch_cached_or_none(now_naive < retry_aware_normalized)
    get_mock.reset_mock()
    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert get_mock.call_count == 0
    assert pf.get_api_status()["source"] == "rate_limited"
    stored = pf._RATE_LIMIT_RETRY_AT
    assert stored is not None
    assert stored.tzinfo is None


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
    assert len(pf._LAST_API_CALL_BY_URL) == 1
    assert next(iter(pf._LAST_API_CALL_BY_URL.values())) >= before
    assert result == [1.5, 2.5, 3.5]


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_429_does_not_update_last_api_call(get_mock, _config_mock, _timeout_mock):
    get_mock.return_value = _429_response(header=(datetime.now() + timedelta(hours=1)).isoformat())

    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert pf._LAST_API_CALL_BY_URL == {}


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


def _http_500_response() -> MagicMock:
    response = MagicMock()
    response.status_code = 500
    response.raise_for_status.side_effect = requests.HTTPError("500", response=response)
    return response


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_http_error_does_not_update_last_api_call(get_mock, _config_mock, _timeout_mock):
    get_mock.return_value = _http_500_response()

    with patch.object(pf, "_open_meteo_pv_vector", return_value=[0.1, 0.2, 0.3]):
        pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert pf._LAST_API_CALL_BY_URL == {}
    assert pf.get_api_status()["open_meteo_systems"] == ["pv"]


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_timeout_with_warm_cache_keeps_api_values(get_mock, _config_mock, _timeout_mock):
    """Nach erfolgreichem Abruf darf Timeout nicht in saisonalen Fallback kippen."""
    get_mock.return_value = _ok_response()
    first = pf.get_hourly_pv_forecast_for_hours(_target_hours())
    assert first == [1.5, 2.5, 3.5]
    assert pf.get_api_status()["open_meteo_systems"] == []

    _age_last_api_calls(timedelta(minutes=20))
    get_mock.side_effect = requests.exceptions.Timeout()

    second = pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert second == [1.5, 2.5, 3.5]
    assert pf.get_api_status()["open_meteo_systems"] == []
    assert pf.get_api_status()["source"] == "cache_after_error"


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_429_with_warm_cache_keeps_api_values(get_mock, _config_mock, _timeout_mock):
    get_mock.return_value = _ok_response()
    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    _age_last_api_calls(timedelta(minutes=20))
    retry_at = datetime.now() + timedelta(hours=1)
    get_mock.return_value = _429_response(header=retry_at.isoformat())

    result = pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert result == [1.5, 2.5, 3.5]
    assert pf.get_api_status()["source_by_system"] == {"pv": pf.SOURCE_FORECAST_SOLAR}
    assert pf.get_api_status()["source"] == "cache_after_error"


def test_parse_retry_at_prefers_header():
    response = MagicMock()
    response.headers = {"X-Ratelimit-Retry-At": "2026-07-15T14:00:00+02:00"}
    response.json.return_value = {
        "message": {"ratelimit": {"retry-at": "2026-07-15T15:00:00+02:00"}}
    }

    parsed = pf._parse_retry_at(response)

    aware = datetime.fromisoformat("2026-07-15T14:00:00+02:00")
    assert parsed == pf._as_naive_local(aware)
    assert parsed.tzinfo is None


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.config.get_planning_pv_systems")
@patch("data.pv_forecast.requests.get")
def test_cooldown_is_per_system_so_every_system_refreshes(
    get_mock, systems_mock, _config_mock, _timeout_mock
):
    """Regression: a shared cooldown stamp let only one PV system refresh per cycle.

    The other system kept its stale cache (missing the next day) for hours.
    """
    systems_mock.return_value = [
        {"id": "south", "pv_kwp": 5.7, "pv_tilt": 18.0, "pv_azimuth": 26.0},
        {"id": "north", "pv_kwp": 6.8, "pv_tilt": 18.0, "pv_azimuth": -154.0},
    ]
    get_mock.return_value = _ok_response()
    pf.get_hourly_pv_forecast_by_system_for_hours(_target_hours())
    assert get_mock.call_count == 2

    # Next cycle 15+ min later: both systems must hit the API again.
    _age_last_api_calls(timedelta(minutes=16))
    get_mock.reset_mock()
    get_mock.return_value = _ok_response(
        {
            "2026-07-15 10:00:00": 500,
            "2026-07-15 11:00:00": 600,
            "2026-07-15 12:00:00": 700,
            "2026-07-15 13:00:00": 800,
        }
    )
    by_system = pf.get_hourly_pv_forecast_by_system_for_hours(_target_hours())

    assert get_mock.call_count == 2
    assert by_system == {"south": [0.55, 0.65, 0.75], "north": [0.55, 0.65, 0.75]}


# ---------------------------------------------------------------------------
# Slot mapping: forecast.solar ``watts`` is the power at the timestamp
# ---------------------------------------------------------------------------


def test_hourly_slot_energy_equals_watt_hours_period():
    """Trapezoid of ``watts`` over the slot = forecast.solar ``watt_hours_period``."""
    watts = {"2026-10-30 12:00:00": 1595, "2026-10-30 13:00:00": 1773}
    hours = [datetime(2026, 10, 30, 12, 0), datetime(2026, 10, 30, 13, 0)]
    vector, ok = pf._map_hourly_data_to_vector(watts, hours)

    assert ok
    assert vector == [1.684, 0.0]


def test_sunrise_and_sunset_points_split_their_hour():
    """Sunrise 07:01 and sunset 17:08 points (0 W) bound the first / last hour."""
    watts = {
        "2026-10-30 07:01:00": 0,
        "2026-10-30 08:00:00": 590,
        "2026-10-30 16:00:00": 1290,
        "2026-10-30 17:00:00": 790,
        "2026-10-30 17:08:00": 0,
    }
    hours = [datetime(2026, 10, 30, 7, 0) + timedelta(hours=i) for i in range(2)]
    hours += [datetime(2026, 10, 30, 16, 0), datetime(2026, 10, 30, 17, 0)]

    vector, ok = pf._map_hourly_data_to_vector(watts, hours[:2])
    assert ok
    # 07–08: 0 → 590 W over 59 min; 08–09 lies on the 08:00 → 16:00 line.
    assert vector[0] == round(590 / 2 * 59 / 60 / 1000, 3)
    assert vector[1] == round((590 + (590 + 700 / 8)) / 2 / 1000, 3)

    vector, ok = pf._map_hourly_data_to_vector(watts, hours[2:])
    assert ok
    # 16–17: mean of 1290 and 790 W; 17–18: 790 → 0 W within 8 min.
    assert vector == [1.04, round(790 / 2 * 8 / 60 / 1000, 3)]


def test_quarter_hour_slots_follow_the_curve():
    watts = {"2026-07-15 10:00:00": 1000, "2026-07-15 11:00:00": 2000}
    slots = [datetime(2026, 7, 15, 10, 0) + timedelta(minutes=15 * i) for i in range(4)]

    vector, ok = pf._map_hourly_data_to_vector(watts, slots)

    assert ok
    assert vector == [1.125, 1.375, 1.625, 1.875]


def test_slots_outside_the_points_are_zero_and_not_counted():
    watts = {"2026-07-15 10:00:00": 1000, "2026-07-15 11:00:00": 2000}
    slots = [datetime(2026, 7, 15, 8, 0), datetime(2026, 7, 15, 9, 0)]

    vector, ok = pf._map_hourly_data_to_vector(watts, slots)

    assert not ok
    assert vector == [0.0, 0.0]


# ---------------------------------------------------------------------------
# Disk cache across restarts
# ---------------------------------------------------------------------------


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_disk_cache_bridges_restart_during_rate_limit(get_mock, _config_mock, _timeout_mock):
    get_mock.return_value = _ok_response()
    pf.get_hourly_pv_forecast_for_hours(_target_hours())

    _restart_process()
    # Restored guard stamp: no forecast.solar call within 15 min after the restart.
    get_mock.reset_mock()
    assert pf.get_hourly_pv_forecast_for_hours(_target_hours()) == [1.5, 2.5, 3.5]
    assert get_mock.call_count == 0

    # Restart 20 min after the last call while forecast.solar answers 429.
    _write_disk_cache(
        {_default_url(): _ok_response().json()["result"]["watts"]},
        datetime.now() - timedelta(minutes=20),
    )
    _restart_process()
    get_mock.return_value = _429_response(header=(datetime.now() + timedelta(hours=1)).isoformat())
    result = pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert get_mock.call_count == 1
    assert result == [1.5, 2.5, 3.5]
    assert pf.get_api_status()["source"] == "cache_after_error"
    assert pf.get_api_status()["source_by_system"] == {"pv": pf.SOURCE_FORECAST_SOLAR}


def _write_disk_cache(url_watts: dict, fetched_at: datetime) -> None:
    import json

    with open(pf._disk_cache_path(), "w", encoding="utf-8") as handle:
        json.dump(
            {
                url: {"fetched_at": fetched_at.isoformat(), "watts": watts}
                for url, watts in url_watts.items()
            },
            handle,
        )


def _default_url() -> str:
    return "https://api.forecast.solar/estimate/51.0/10.0/35.0/0.0/6.0"


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_disk_cache_older_than_limit_is_not_used(get_mock, _config_mock, _timeout_mock):
    _write_disk_cache(
        {_default_url(): {"2026-07-15 10:00:00": 9000}},
        datetime.now() - pf.DISK_CACHE_MAX_AGE - timedelta(minutes=5),
    )
    get_mock.return_value = _http_500_response()

    with patch.object(pf, "_open_meteo_pv_vector", return_value=[0.4, 0.5, 0.6]):
        result = pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert get_mock.call_count == 1
    assert result == [0.4, 0.5, 0.6]
    assert pf.get_api_status()["open_meteo_systems"] == ["pv"]


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_fresh_disk_cache_is_used_after_api_error(get_mock, _config_mock, _timeout_mock):
    _write_disk_cache(
        {
            _default_url(): {
                "2026-07-15 10:00:00": 4000,
                "2026-07-15 11:00:00": 5000,
                "2026-07-15 12:00:00": 6000,
            }
        },
        datetime.now() - timedelta(hours=2),
    )
    get_mock.return_value = _http_500_response()

    result = pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert result == [4.5, 5.5, 0.0]
    assert pf.get_api_status()["source"] == "cache_after_error"
    assert pf.get_api_status()["source_by_system"] == {"pv": pf.SOURCE_FORECAST_SOLAR}


# ---------------------------------------------------------------------------
# Open-Meteo substitute and hard failure (no synthetic curve)
# ---------------------------------------------------------------------------


def test_open_meteo_vector_uses_orientation_and_preceding_hour_mean():
    calls: list[dict] = []

    def fake_gti(**kwargs):
        calls.append(kwargs)
        # Stamps start, start+1h, …: mean of the hour ending at the stamp.
        return [0.0, 500.0, 1000.0, 250.0][: kwargs["horizon"]]

    base = datetime(2026, 10, 30, 10, 0)
    targets = [base, base + timedelta(minutes=15), base + timedelta(hours=1), base + timedelta(hours=2)]
    with patch("data.outdoor_forecast.get_hourly_tilted_irradiance_forecast_wm2", side_effect=fake_gti):
        vector = pf._open_meteo_pv_vector(
            lat=51.0, lon=10.0, tilt=18.0, azimuth=-154.0, kwp=6.8, target_hours=targets
        )

    assert calls == [
        {
            "horizon": 4,
            "tilt_deg": 18.0,
            "azimuth_deg": -154.0,
            "latitude": 51.0,
            "longitude": 10.0,
            "start": base,
        }
    ]
    # Slot 10:00 ← stamp 11:00 (500 W/m²), QH 10:15 inherits 10:00.
    assert vector == [3.4, 3.4, 6.8, 1.7]


@patch("data.pv_forecast.config.get_global_timeout", return_value=10)
@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.requests.get")
def test_no_forecast_solar_and_no_open_meteo_raises(get_mock, _config_mock, _timeout_mock):
    get_mock.return_value = _http_500_response()

    with patch(
        "data.outdoor_forecast.get_hourly_tilted_irradiance_forecast_wm2",
        side_effect=RuntimeError("offline"),
    ):
        with pytest.raises(pf.PvForecastUnavailableError, match="offline"):
            pf.get_hourly_pv_forecast_for_hours(_target_hours())

    assert pf.get_api_status()["source_by_system"] == {}


@patch("data.pv_forecast.config.get", side_effect=_config_get_side_effect)
@patch("data.pv_forecast.config.get_planning_pv_systems")
def test_open_meteo_only_for_system_without_forecast_solar(systems_mock, _config_mock):
    systems_mock.return_value = [
        {"id": "south", "pv_kwp": 5.7, "pv_tilt": 18.0, "pv_azimuth": 26.0},
        {"id": "north", "pv_kwp": 6.8, "pv_tilt": 18.0, "pv_azimuth": -154.0},
    ]

    def fake_fetch(url, kwp):
        if "/26.0/" in url:
            return {
                "2026-07-15 10:00:00": 1000,
                "2026-07-15 11:00:00": 1000,
                "2026-07-15 12:00:00": 1000,
                "2026-07-15 13:00:00": 1000,
            }
        return None

    with patch.object(pf, "_check_and_fetch_api_data", side_effect=fake_fetch), patch.object(
        pf, "_open_meteo_pv_vector", return_value=[0.2, 0.2, 0.2]
    ) as om_mock:
        by_system = pf.get_hourly_pv_forecast_by_system_for_hours(_target_hours())

    assert by_system == {"south": [1.0, 1.0, 1.0], "north": [0.2, 0.2, 0.2]}
    assert om_mock.call_args.kwargs["azimuth"] == -154.0
    status = pf.get_api_status()
    assert status["source_by_system"] == {
        "south": pf.SOURCE_FORECAST_SOLAR,
        "north": pf.SOURCE_OPEN_METEO,
    }
    assert status["open_meteo_systems"] == ["north"]


# ---------------------------------------------------------------------------
# Shadow: forecast.solar feed outlives the per-cycle max age
# ---------------------------------------------------------------------------


def test_shadow_replay_uses_pv_feed_max_age():
    captured: dict = {}

    def fake_replay(key, *, max_age_s=None):
        captured["key"] = key
        captured["max_age_s"] = max_age_s
        return {"result": {"watts": {"2026-07-15 10:00:00": 1500}}}

    with patch("runtime_store.shadow.mode.is_shadow_mode", return_value=True), patch(
        "runtime_store.shadow.transport.is_shadow_mode", return_value=True
    ), patch("runtime_store.shadow.replay.replay_ext_payload", side_effect=fake_replay):
        watts = pf._check_and_fetch_api_data(_default_url(), 6.0)

    assert watts == {"2026-07-15 10:00:00": 1500}
    assert captured["key"].startswith("ext:pv_forecast:")
    assert captured["max_age_s"] == pf.SHADOW_FEED_MAX_AGE_SEC
    assert pf.get_api_status()["source"] == "shadow_feed"


def test_shadow_record_staleness_honours_per_feed_max_age():
    from datetime import timezone

    from runtime_store.shadow.replay import is_record_stale, max_age_sec

    ref = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    ten_min_old = {"ts": (ref - timedelta(minutes=10)).isoformat()}
    four_h_old = {"ts": (ref - timedelta(hours=4)).isoformat()}

    assert max_age_sec() < 600
    assert is_record_stale(ten_min_old, ref_ts=ref.isoformat())
    assert not is_record_stale(
        ten_min_old, ref_ts=ref.isoformat(), max_age_s=pf.SHADOW_FEED_MAX_AGE_SEC
    )
    assert is_record_stale(
        four_h_old, ref_ts=ref.isoformat(), max_age_s=pf.SHADOW_FEED_MAX_AGE_SEC
    )
