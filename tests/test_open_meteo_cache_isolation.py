"""Tests must never write mock climate data into the repo's Open-Meteo cache."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from data import open_meteo_solar_archive as archive
from data.open_meteo_solar_archive import TiltedSurface

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_CACHE_DIR = (REPO_ROOT / "data" / "cache" / "open_meteo").resolve()


def _repo_cache_files() -> set[str]:
    if not REPO_CACHE_DIR.is_dir():
        return set()
    return {path.name for path in REPO_CACHE_DIR.iterdir()}


def test_open_meteo_cache_dir_is_outside_repo_during_tests():
    cache_dir = Path(archive.OPEN_METEO_CACHE_DIR).resolve()
    assert cache_dir != REPO_CACHE_DIR
    assert REPO_ROOT not in cache_dir.parents


def test_mocked_climate_bundle_does_not_touch_repo_cache(monkeypatch):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    monkeypatch.setattr(archive, "archive_latest_complete_date", lambda: date(2025, 12, 31))
    before = _repo_cache_files()

    archive.build_open_meteo_climate_bundle(
        date(2025, 6, 1),
        date(2025, 6, 30),
        lat=12.3456,
        lon=65.4321,
        timezone="Europe/Vienna",
        surfaces=[TiltedSurface(18.0, 0.0)],
    )

    assert _repo_cache_files() == before
    written = list(Path(archive.OPEN_METEO_CACHE_DIR).glob("12.3456_65.4321_*.json"))
    assert len(written) == 1


def test_cache_path_env_override_wins_over_module_default(monkeypatch, tmp_path):
    surfaces = [TiltedSurface(tilt_deg=18.0, azimuth_deg=0.0)]
    args = (47.4, 9.7, "Europe/Vienna", date(2025, 1, 1), date(2025, 12, 31), surfaces)
    default_path = archive.open_meteo_cache_path(*args)
    monkeypatch.setenv("EARNIE_OPEN_METEO_CACHE_PATH", str(tmp_path))
    overridden = archive.open_meteo_cache_path(*args)
    assert overridden.parent == tmp_path
    assert overridden.name == default_path.name
