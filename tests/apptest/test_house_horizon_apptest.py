"""Hauskonfigurator (SUSI P3a): manual horizon as 16 bars, north to north.

The fixture house ``test_home`` has no horizon. The switch shows the bar editor (a Streamlit
component, which AppTest mounts but cannot operate: the tests set its state). Every change
is auto-saved into ``house_profiles.json``. Switched off, the list stays stored with
``horizon_source: none``.
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
_BARS = "house-horizon-bars-test_home"
_SOUTH = 8
_EAST = 4


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


def _set_bars(at: AppTest, **by_index: float) -> AppTest:
    """What the component sends when a bar is released: the whole list of elevations."""
    elevations = list(at.session_state[_BARS]["elevations"])
    for index, value in by_index.items():
        elevations[int(index.removeprefix("i"))] = value
    at.session_state[_BARS] = {"elevations": elevations}
    return _run(at)


def _stored() -> dict[float, float]:
    return {p["azimuth_deg"]: p["elevation_deg"] for p in _raw_profile()["horizon"]}


def test_house_without_horizon_shows_the_switch_only() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    assert at.checkbox(key=_ENABLED).value is False
    assert _BARS not in at.session_state
    raw = _raw_profile()
    assert "horizon" not in raw and "horizon_source" not in raw


def test_switch_shows_the_bars_and_saves_16_directions() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    at.checkbox(key=_ENABLED).set_value(True)
    at = _run(at)
    assert at.session_state[_BARS]["elevations"] == [0.0] * 16
    assert any("Neigungsmesser-App" in c.value for c in at.caption)
    assert _raw_profile()["horizon_source"] == "manual"
    at = _set_bars(at, **{f"i{_SOUTH}": 12.0, f"i{_EAST}": 30.0})
    stored = _stored()
    assert len(stored) == 16
    assert stored[0.0] == 12.0
    assert stored[-90.0] == 30.0
    assert stored[90.0] == 0.0


def test_direction_the_sun_never_reaches_is_stored_as_zero() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    at.checkbox(key=_ENABLED).set_value(True)
    at = _run(at)
    at = _set_bars(at, i0=25.0, **{f"i{_SOUTH}": 12.0})
    stored = _stored()
    assert stored[-180.0] == 0.0
    assert stored[0.0] == 12.0


def test_switched_off_horizon_stays_stored_and_comes_back() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    at.checkbox(key=_ENABLED).set_value(True)
    at = _run(at)
    at = _set_bars(at, **{f"i{_SOUTH}": 12.0})
    at.checkbox(key=_ENABLED).set_value(False)
    at = _run(at)
    raw = _raw_profile()
    assert raw["horizon_source"] == "none"
    assert _stored()[0.0] == 12.0
    # A new session reads the stored list when the switch is turned on again.
    fresh = _run(AppTest.from_file(str(_SCRIPT)))
    assert fresh.checkbox(key=_ENABLED).value is False
    fresh.checkbox(key=_ENABLED).set_value(True)
    fresh = _run(fresh)
    assert fresh.session_state[_BARS]["elevations"][_SOUTH] == 12.0
    assert _raw_profile()["horizon_source"] == "manual"
