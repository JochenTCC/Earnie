r"""Run ``studies.viability.inspect_pack`` on committed Open-Meteo climate only (no network, no local cache).

Loading a pack with a fuel or heat-pump heating derives the thermal parameters from one calendar year of the
Open-Meteo archive. Without this runner the test reads ``data/cache/open_meteo_utc`` (filled on a dev machine,
empty on CI) and otherwise fetches a whole year from the archive, which times out on CI runners. The year is
pinned by ``EARNIE_CLIMATE_REFERENCE_YEAR`` (set by the caller), so the cache key does not follow the clock.

Re-record after a deliberate change of house location, surfaces or year (needs network)::

    $env:EARNIE_VIABILITY_RECORD_CLIMATE='1'
    .venv\Scripts\python.exe -m scripts.run_pytest tests/test_viability_generator.py -q -n 0
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "viability_open_meteo"
RECORD_ENV = "EARNIE_VIABILITY_RECORD_CLIMATE"


class ClimateFixtureMissingError(RuntimeError):
    """The pack asked for Open-Meteo data that is not in the committed fixture."""


def _refuse_archive_fetch(*, lat, lon, timezone, start, end, hourly_vars, extra_params=None, **_):
    raise ClimateFixtureMissingError(
        f"Viability climate fixture missing in {FIXTURE_DIR}: lat={lat} lon={lon} tz={timezone} "
        f"{start}..{end} vars={hourly_vars} params={extra_params}. Re-record with {RECORD_ENV}=1 "
        "(see tests/fixtures/viability_inspect_offline.py); the test never falls back to the network."
    )


def main() -> None:
    from data import open_meteo_solar_archive as archive

    os.environ.pop("EARNIE_OPEN_METEO_CACHE_PATH", None)
    archive.OPEN_METEO_CACHE_DIR = FIXTURE_DIR
    if os.environ.get(RECORD_ENV) != "1":
        archive._fetch_hourly_archive_chunk = _refuse_archive_fetch
    runpy.run_module("studies.viability.inspect_pack", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
