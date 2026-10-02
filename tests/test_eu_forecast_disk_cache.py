"""Tests for EU forecast disk cache (research path)."""
from __future__ import annotations

import json
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data import eu_forecast_disk_cache as disk

VIENNA = ZoneInfo("Europe/Vienna")


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        disk,
        "cache_dir",
        lambda: tmp_path / "cache",
    )
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    return tmp_path / "cache"


def _sample_frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [datetime(2025, 7, 1, 12, 0, tzinfo=VIENNA)],
        name="slot_datetime",
    )
    return pd.DataFrame(
        {"eu_wind_mw": [100.0], "eu_solar_mw": [50.0]},
        index=idx,
    )


def test_save_and_load_frame_roundtrip(cache_root):
    start, end = date(2025, 7, 1), date(2025, 7, 2)
    frame = _sample_frame()
    disk.save_frame(disk.KIND_POWER, start, end, frame)
    loaded, age, fresh = disk.load_frame(disk.KIND_POWER, start, end, ttl_sec=3600)
    assert loaded is not None
    assert fresh is True
    assert age is not None and age < 5
    assert abs(float(loaded["eu_wind_mw"].iloc[0]) - 100.0) < 1e-9


def test_load_frame_stale_when_past_ttl(cache_root):
    start, end = date(2025, 7, 1), date(2025, 7, 2)
    path = disk.frame_path(disk.KIND_POWER, start, end)
    payload = {
        "fetched_at": time.time() - 10_000,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "index": [datetime(2025, 7, 1, 12, 0, tzinfo=VIENNA).isoformat()],
        "columns": {"eu_wind_mw": [1.0], "eu_solar_mw": [2.0]},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded, age, fresh = disk.load_frame(disk.KIND_POWER, start, end, ttl_sec=60)
    assert loaded is not None
    assert fresh is False
    assert age is not None and age > 1000


def test_save_frame_atomic_replace(cache_root):
    start, end = date(2025, 7, 1), date(2025, 7, 2)
    disk.save_frame(disk.KIND_POWER, start, end, _sample_frame())
    assert disk.frame_path(disk.KIND_POWER, start, end).is_file()
    assert not list(cache_root.glob("*.tmp"))


def test_get_status_inactive_for_archive_hod(cache_root):
    status = disk.get_eu_forecast_cache_status(
        eu_power_live_source="archive_hod",
        missing_price_strategy="forecast",
        live_bias_enabled=False,
    )
    assert status["state"] == disk.STATE_INACTIVE


def test_get_status_ready_when_both_fresh(cache_root):
    start, end = date(2025, 7, 1), date(2025, 7, 2)
    disk.save_frame(disk.KIND_POWER, start, end, _sample_frame())
    disk.save_frame(disk.KIND_WEATHER, start, end, _sample_frame())
    disk.write_status(
        {
            "state": disk.STATE_READY,
            "range_start": start.isoformat(),
            "range_end": end.isoformat(),
            "fetched_at": time.time(),
            "eu_power_live_source": "energy_charts_forecast",
        }
    )
    status = disk.get_eu_forecast_cache_status(
        eu_power_live_source="energy_charts_forecast",
        ttl_sec=3600,
    )
    assert status["state"] == disk.STATE_READY
    assert status["power_fresh"] is True
    assert status["weather_fresh"] is True


def test_get_status_warming(cache_root):
    disk.mark_warming(
        date(2025, 7, 1),
        date(2025, 7, 2),
        eu_power_live_source="energy_charts_forecast",
    )
    status = disk.get_eu_forecast_cache_status(
        eu_power_live_source="energy_charts_forecast",
    )
    assert status["state"] == disk.STATE_WARMING
