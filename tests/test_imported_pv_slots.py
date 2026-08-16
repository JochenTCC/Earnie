"""Tests for use_imported_pv in HistoricalDataCache.get_pv_for_slots."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from house_config.consumption_csv import MIN_HOURS_FULL_YEAR, write_canonical_hourly_csv
from simulation.engine import (
    HistoricalDataCache,
    collect_imported_pv_scenario_meta,
    scenario_uses_imported_pv,
)


def _write_pv_csv(path: Path, *, hours: int = 48, power_kw: float = 2.5) -> None:
    start = datetime(2023, 1, 1)
    rows = [
        ((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), power_kw)
        for i in range(hours)
    ]
    write_canonical_hourly_csv(str(path), rows)


def test_scenario_uses_imported_pv_requires_adequate_csv(tmp_path: Path) -> None:
    assert not scenario_uses_imported_pv({"use_imported_pv": True})
    short = tmp_path / "short_pv.csv"
    full = tmp_path / "full_pv.csv"
    _write_pv_csv(short, hours=100)
    _write_pv_csv(full, hours=MIN_HOURS_FULL_YEAR)
    assert not scenario_uses_imported_pv(
        {
            "use_imported_pv": True,
            "_house_profile": {"pv_profile_csv": str(short)},
        }
    )
    assert scenario_uses_imported_pv(
        {
            "use_imported_pv": True,
            "_house_profile": {"pv_profile_csv": str(full)},
        }
    )
    assert not scenario_uses_imported_pv(
        {
            "use_imported_pv": True,
            "_house_profile": {"pv_profile_csv": "config/uploads/missing.csv"},
        }
    )


def test_get_pv_for_slots_uses_imported_csv(tmp_path: Path) -> None:
    pv_path = tmp_path / "pv.csv"
    _write_pv_csv(pv_path, hours=MIN_HOURS_FULL_YEAR, power_kw=3.0)
    cache = HistoricalDataCache()
    slots = [datetime(2023, 1, 1, hour=h) for h in range(24)]
    values = cache.get_pv_for_slots(
        slots,
        scenario_params={
            "use_imported_pv": True,
            "_house_profile": {"pv_profile_csv": str(pv_path)},
            "_planning_pv_systems": [],
        },
    )
    assert len(values) == 24
    assert values[0] == pytest.approx(3.0)


def test_get_pv_for_slots_falls_back_when_short_csv(tmp_path: Path, monkeypatch) -> None:
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    pv_path = tmp_path / "short.csv"
    _write_pv_csv(pv_path, hours=48, power_kw=9.0)
    cache = HistoricalDataCache()
    slots = [datetime(2023, 6, 15, 12, 0)]
    values = cache.get_pv_for_slots(
        slots,
        scenario_params={
            "use_imported_pv": True,
            "_house_profile": {
                "pv_profile_csv": str(pv_path),
                "latitude": 48.0,
                "longitude": 16.0,
            },
            "latitude": 48.0,
            "longitude": 16.0,
            "_planning_pv_systems": [],
        },
    )
    # Short import → synthetic/weather path (not constant 9.0 from CSV).
    assert values != [9.0]


def test_get_pv_for_slots_falls_back_when_flag_without_csv(monkeypatch) -> None:
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    cache = HistoricalDataCache()
    slots = [datetime(2023, 6, 15, 12, 0)]
    values = cache.get_pv_for_slots(
        slots,
        scenario_params={
            "use_imported_pv": True,
            "_house_profile": {
                "pv_profile_csv": "",
                "latitude": 48.0,
                "longitude": 16.0,
            },
            "latitude": 48.0,
            "longitude": 16.0,
            "_planning_pv_systems": [],
        },
    )
    assert values == [0.0]


def test_collect_imported_pv_scenario_meta(tmp_path: Path) -> None:
    full = tmp_path / "full.csv"
    _write_pv_csv(full, hours=MIN_HOURS_FULL_YEAR)
    used, missing = collect_imported_pv_scenario_meta(
        {
            "a": {
                "use_imported_pv": True,
                "_house_profile": {"pv_profile_csv": str(full)},
            },
            "b": {"use_imported_pv": True, "_house_profile": {}},
            "c": {"use_imported_pv": False},
            "d": {
                "use_imported_pv": True,
                "_house_profile": {"pv_profile_csv": str(tmp_path / "missing.csv")},
            },
        }
    )
    assert used == ["a"]
    assert missing == ["b", "d"]
