"""Prefetch of slow Live inputs (EarlyStart follow-up, spec §8)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd

import main as main_module
from data import live_prefetch
from data import price_forecast_live as pfl
from runtime_store.planning_clock import cache_valid_until


def _weather(start: datetime, hours: int) -> pd.DataFrame:
    index = pd.date_range(start, periods=hours, freq="h")
    return pd.DataFrame({"eu_wind_speed_kmh": 1.0, "eu_shortwave_radiation_wm2": 2.0}, index=index)


def test_feature_input_cache_is_keyed_by_days_not_by_hours():
    pfl._feature_input_cache.clear()
    calls = []

    def fetch():
        calls.append(1)
        return _weather(datetime(2026, 10, 15), 72)

    start, end = datetime(2026, 10, 15).date(), datetime(2026, 10, 18).date()
    first = pfl._cached_feature_input("forecast_weather", start, end, fetch)
    # Next hour: the planning window moved, its calendar days did not.
    second = pfl._cached_feature_input("forecast_weather", start, end, fetch)
    assert len(calls) == 1
    assert second is first


def test_feature_input_cache_refreshes_ahead_inside_valid_until():
    pfl._feature_input_cache.clear()
    calls = []

    def fetch():
        calls.append(1)
        return _weather(datetime(2026, 10, 15), 24)

    day = datetime(2026, 10, 15).date()
    pfl._cached_feature_input("forecast_weather", day, day, fetch)
    horizon = datetime.now() + timedelta(seconds=pfl.LIVE_FEATURE_CACHE_TTL_SEC + 60)
    with cache_valid_until(horizon):
        pfl._cached_feature_input("forecast_weather", day, day, fetch)
    assert len(calls) == 2


def test_prefetch_step_failure_is_logged_not_raised(caplog):
    window = object()
    with patch.object(live_prefetch, "_prefetch_prices", side_effect=RuntimeError("503")):
        with patch.object(live_prefetch, "_prefetch_thermal_weather") as weather:
            with patch(
                "data.profile_manager.compute_live_planning_window", return_value=window
            ):
                with caplog.at_level(logging.WARNING, logger="data.live_prefetch"):
                    result = live_prefetch.prefetch_live_inputs(
                        datetime(2026, 10, 15, 15, 0), datetime(2026, 10, 15, 14, 59, 30)
                    )
    weather.assert_called_once_with(window)
    assert result.errors and "Preise" in result.errors[0]
    assert any("Prefetch Preise fehlgeschlagen" in r.getMessage() for r in caplog.records)


def test_daemon_skips_prefetch_when_next_start_is_close(monkeypatch):
    calls = []
    monkeypatch.setattr(live_prefetch, "prefetch_live_inputs", lambda *a: calls.append(a))
    soon = datetime.now() + timedelta(seconds=live_prefetch.MIN_IDLE_SEC - 10)
    main_module._prefetch_for_next_cycle(soon + timedelta(seconds=30), soon)
    assert calls == []
    later = datetime.now() + timedelta(minutes=10)
    main_module._prefetch_for_next_cycle(later + timedelta(seconds=30), later)
    assert len(calls) == 1


def test_daemon_survives_prefetch_crash(monkeypatch, caplog):
    def boom(*_a):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(live_prefetch, "prefetch_live_inputs", boom)
    later = datetime.now() + timedelta(minutes=10)
    with caplog.at_level(logging.WARNING, logger="main"):
        main_module._prefetch_for_next_cycle(later, later)
    assert any("Prefetch für" in r.getMessage() for r in caplog.records)
