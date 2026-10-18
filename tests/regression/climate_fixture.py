"""Frozen Open-Meteo climate input for L2 regression runs (no network, no local cache).

L2 cases read irradiance and temperature through the Open-Meteo archive cache.
Without this, results depend on ``data/cache/open_meteo`` (mutable, shared with
the app and — before the conftest fix — with pytest mocks) and on the live
archive whenever a cache key is missing. Cache keys contain the last complete
archive day and the last full archive year, both derived from the wall clock,
so the clock is frozen at :data:`CLIMATE_FIXTURE_NOW` as well.

Re-record after a deliberate fixture change (needs network)::

    $env:EARNIE_REGRESSION_RECORD_CLIMATE='1'
    .venv\\Scripts\\python.exe -m scripts.run_regression --workers 1
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator
from zoneinfo import ZoneInfo

import time_machine

from tests.fixtures.backtesting_fixtures import FIXTURES_ROOT

CLIMATE_FIXTURE_DIR = FIXTURES_ROOT / "open_meteo"
# Recording date of the committed climate files (last archive day 2026-10-17).
CLIMATE_FIXTURE_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=ZoneInfo("Europe/Vienna"))
RECORD_ENV = "EARNIE_REGRESSION_RECORD_CLIMATE"


class ClimateFixtureMissingError(RuntimeError):
    """An L2 run asked for Open-Meteo data that is not in the committed fixture."""


def _refuse_archive_fetch(*, lat, lon, timezone, start, end, hourly_vars, extra_params=None):
    raise ClimateFixtureMissingError(
        f"L2 climate fixture missing in {CLIMATE_FIXTURE_DIR}: "
        f"lat={lat} lon={lon} tz={timezone} {start}..{end} vars={hourly_vars} "
        f"params={extra_params}. Re-record with {RECORD_ENV}=1 "
        "(see tests/regression/climate_fixture.py) — never falls back to the network."
    )


@contextmanager
def frozen_climate_fixture() -> Iterator[None]:
    """Freeze the clock and serve Open-Meteo data only from the committed fixture."""
    from data import open_meteo_solar_archive as archive

    recording = os.environ.get(RECORD_ENV) == "1"
    previous_dir = archive.OPEN_METEO_CACHE_DIR
    previous_fetch = archive._fetch_hourly_archive_chunk
    archive.OPEN_METEO_CACHE_DIR = CLIMATE_FIXTURE_DIR
    if not recording:
        archive._fetch_hourly_archive_chunk = _refuse_archive_fetch
    archive.clear_open_meteo_bundle_mem_cache()
    try:
        with time_machine.travel(CLIMATE_FIXTURE_NOW, tick=True):
            yield
    finally:
        archive.OPEN_METEO_CACHE_DIR = previous_dir
        archive._fetch_hourly_archive_chunk = previous_fetch
        archive.clear_open_meteo_bundle_mem_cache()
