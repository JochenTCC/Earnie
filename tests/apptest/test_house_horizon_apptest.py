"""Hauskonfigurator (SUSI P3a): manual horizon in 16 directions.

The fixture house ``test_home`` has no horizon. The switch shows the table and the preview;
every change is auto-saved into ``house_profiles.json``. Switched off, the list stays stored
with ``horizon_source: none``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.apptest.helpers import assert_clean

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_PREFIX = "test_home__"
_ENABLED = f"{_PREFIX}house_horizon_enabled"
_SOUTH = f"{_PREFIX}house_horizon_elevation_8"
_NORTH = f"{_PREFIX}house_horizon_elevation_0"


@pytest.fixture(autouse=True)
def _isolated(_isolated_backtesting_config):
    from house_config.components_store import clear_components_doc_cache
    from house_config.profiles_store import clear_house_profiles_doc_cache
    from tests.conftest import _reinit_config_offline

    clear_components_doc_cache()
    clear_house_profiles_doc_cache()
    _reinit_config_offline()
    yield


def _run(at: AppTest) -> AppTest:
    at.run(timeout=_TIMEOUT_S)
    assert_clean(at)
    assert not at.error, [e.value for e in at.error]
    return at


def _raw_profile() -> dict:
    doc = json.loads(Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"]).read_text(encoding="utf-8"))
    return next(p for p in doc["profiles"] if p["id"] == "test_home")


def _keys(at: AppTest) -> set[str]:
    return {w.key for w in at.number_input}


def test_house_without_horizon_shows_the_switch_only() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    assert at.checkbox(key=_ENABLED).value is False
    assert _SOUTH not in _keys(at)
    raw = _raw_profile()
    assert "horizon" not in raw and "horizon_source" not in raw


def test_switch_shows_16_directions_and_saves_them() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    at.checkbox(key=_ENABLED).set_value(True)
    at = _run(at)
    elevation_keys = {k for k in _keys(at) if k.startswith(f"{_PREFIX}house_horizon_elevation_")}
    assert len(elevation_keys) == 16
    assert at.number_input(key=_SOUTH).value == 0.0
    assert any("Neigungsmesser-App" in c.value for c in at.caption)
    at.number_input(key=_SOUTH).set_value(12.0)
    at = _run(at)
    at.number_input(key=_NORTH).set_value(30.0)
    at = _run(at)
    raw = _raw_profile()
    assert raw["horizon_source"] == "manual"
    by_azimuth = {p["azimuth_deg"]: p["elevation_deg"] for p in raw["horizon"]}
    assert len(by_azimuth) == 16
    assert by_azimuth[0.0] == 12.0
    assert by_azimuth[-180.0] == 30.0
    assert by_azimuth[90.0] == 0.0


def test_switched_off_horizon_stays_stored_and_comes_back() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    at.checkbox(key=_ENABLED).set_value(True)
    at = _run(at)
    at.number_input(key=_SOUTH).set_value(12.0)
    at = _run(at)
    at.checkbox(key=_ENABLED).set_value(False)
    at = _run(at)
    raw = _raw_profile()
    assert raw["horizon_source"] == "none"
    assert {p["azimuth_deg"]: p["elevation_deg"] for p in raw["horizon"]}[0.0] == 12.0
    assert _SOUTH not in _keys(at)
    # A new session reads the stored list when the switch is turned on again.
    fresh = _run(AppTest.from_file(str(_SCRIPT)))
    assert fresh.checkbox(key=_ENABLED).value is False
    fresh.checkbox(key=_ENABLED).set_value(True)
    fresh = _run(fresh)
    assert fresh.number_input(key=_SOUTH).value == 12.0
    assert _raw_profile()["horizon_source"] == "manual"
