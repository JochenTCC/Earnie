"""Frozen Open-Meteo climate input for regression runs (no network, no local cache).

L2 cases read irradiance and temperature through the Open-Meteo archive cache.
L1 replays read it too: the MILP's thermal flex context models heat-pump / pool
consumers from a calendar-year climate bundle at the config snapshot's lat/lon,
which the recorded cycle does not carry. Without this, results depend on
``data/cache/open_meteo`` (mutable, shared with the app and — before the conftest
fix — with pytest mocks) and on the live archive whenever a cache key is missing.
Cache keys contain the last complete archive day and the last full archive year,
both derived from the wall clock, so the clock is frozen at
:data:`CLIMATE_FIXTURE_NOW` as well.

Re-record after a deliberate fixture change (needs network)::

    $env:EARNIE_REGRESSION_RECORD_CLIMATE='1'
    .venv\\Scripts\\python.exe -m scripts.run_regression --workers 1
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import time_machine

from tests.fixtures.backtesting_fixtures import FIXTURES_ROOT

CLIMATE_FIXTURE_DIR = FIXTURES_ROOT / "open_meteo"
# L1 recorder fixtures (tests/regression/fixtures/) carry their own climate.
L1_CLIMATE_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "open_meteo"
# Recording date of the committed climate files (last archive day 2026-10-17).
CLIMATE_FIXTURE_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=ZoneInfo("Europe/Vienna"))
RECORD_ENV = "EARNIE_REGRESSION_RECORD_CLIMATE"
_CACHE_PATH_ENV = "EARNIE_OPEN_METEO_CACHE_PATH"


class ClimateFixtureMissingError(RuntimeError):
    """A regression run asked for Open-Meteo data that is not in the committed fixture."""


def _refusing_fetch(fixture_dir: Path):
    def _refuse_archive_fetch(*, lat, lon, timezone, start, end, hourly_vars, extra_params=None):
        raise ClimateFixtureMissingError(
            f"Regression climate fixture missing in {fixture_dir}: "
            f"lat={lat} lon={lon} tz={timezone} {start}..{end} vars={hourly_vars} "
            f"params={extra_params}. Re-record with {RECORD_ENV}=1 "
            "(see tests/regression/climate_fixture.py) — never falls back to the network."
        )

    return _refuse_archive_fetch


@contextmanager
def frozen_climate_fixture(fixture_dir: Path = CLIMATE_FIXTURE_DIR) -> Iterator[set[Path]]:
    """Freeze the clock and serve Open-Meteo data only from ``fixture_dir``.

    Yields the set of fixture files the block read (or recorded); callers digest
    them into the input fingerprint.
    """
    from data import open_meteo_solar_archive as archive

    recording = os.environ.get(RECORD_ENV) == "1"
    used: set[Path] = set()
    previous_dir = archive.OPEN_METEO_CACHE_DIR
    previous_env = os.environ.pop(_CACHE_PATH_ENV, None)
    previous_fetch = archive._fetch_hourly_archive_chunk
    previous_load = archive._load_bundle_from_cache
    previous_save = archive._save_bundle_to_cache

    def _tracking_load(lat, lon, timezone, start, end, surfaces, *, cache_dir=None):
        bundle = previous_load(lat, lon, timezone, start, end, surfaces, cache_dir=cache_dir)
        if bundle is not None:
            used.add(archive.open_meteo_cache_path(
                lat, lon, timezone, start, end, surfaces, cache_dir=cache_dir
            ))
        return bundle

    def _tracking_save(bundle, lat, lon, timezone, start, end, surfaces, *, cache_dir=None):
        previous_save(bundle, lat, lon, timezone, start, end, surfaces, cache_dir=cache_dir)
        used.add(archive.open_meteo_cache_path(
            lat, lon, timezone, start, end, surfaces, cache_dir=cache_dir
        ))

    archive.OPEN_METEO_CACHE_DIR = fixture_dir
    archive._load_bundle_from_cache = _tracking_load
    archive._save_bundle_to_cache = _tracking_save
    if not recording:
        archive._fetch_hourly_archive_chunk = _refusing_fetch(fixture_dir)
    archive.clear_open_meteo_bundle_mem_cache()
    try:
        with time_machine.travel(CLIMATE_FIXTURE_NOW, tick=True):
            yield used
    finally:
        archive.OPEN_METEO_CACHE_DIR = previous_dir
        archive._fetch_hourly_archive_chunk = previous_fetch
        archive._load_bundle_from_cache = previous_load
        archive._save_bundle_to_cache = previous_save
        if previous_env is not None:
            os.environ[_CACHE_PATH_ENV] = previous_env
        archive.clear_open_meteo_bundle_mem_cache()
