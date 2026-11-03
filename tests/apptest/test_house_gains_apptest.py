"""Hauskonfigurator (SUSI P2): solar gains, gross floor area and the Grundlast gain factor.

The fixture house ``test_home`` has heating on and the migrated ``solar_gains`` block (off,
SUSI window suggestion). Turning the switch on shows the window fields; every change is
auto-saved into ``house_profiles.json``.
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
_SOLAR = f"{_PREFIX}house_solar_enabled"
_WINDOW_S = f"{_PREFIX}house_window_s"
_GROSS_USE = f"{_PREFIX}house_thermal_gross_use"
_GROSS = f"{_PREFIX}house_thermal_gross"
_BASELOAD_GAIN = f"{_PREFIX}house_baseload_gain"


@pytest.fixture(autouse=True)
def _isolated(_isolated_backtesting_config):
    from house_config.components_store import clear_components_doc_cache
    from house_config.profiles_store import clear_house_profiles_doc_cache
    from tests.conftest import _reinit_config_offline

    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    house = json.loads(path.read_text(encoding="utf-8"))
    house["profiles"][0]["annual_kwh"] = 200000.0
    path.write_text(json.dumps(house, ensure_ascii=False), encoding="utf-8")
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


def test_solar_switch_shows_windows_and_saves_them(monkeypatch) -> None:
    # The offline climate has no hourly window irradiance: keep the year model out of it.
    monkeypatch.setattr(
        "ui.house_config_profile_thermal_annual._render_wp_annual_metric",
        lambda *_a, **_k: None,
        raising=False,
    )
    at = _run(AppTest.from_file(str(_SCRIPT)))
    assert at.checkbox(key=_SOLAR).value is False
    assert _WINDOW_S not in _keys(at)
    at.checkbox(key=_SOLAR).set_value(True)
    at = _run(at)
    assert at.number_input(key=_WINDOW_S).value == 10.0
    assert any("Vorschlag nach SUSI" in c.value for c in at.caption)
    at.number_input(key=_WINDOW_S).set_value(14.0)
    at = _run(at)
    solar = _raw_profile()["thermal"]["solar_gains"]
    assert solar["enabled"] is True
    assert solar["window_area_m2"]["s"] == 14.0


def test_gross_floor_area_and_baseload_gain_are_saved() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    assert any("Wohnfläche × 1,25 = 125 m²" in c.value for c in at.caption)
    at.checkbox(key=_GROSS_USE).set_value(True)
    at = _run(at)
    at.number_input(key=_GROSS).set_value(150.0)
    at = _run(at)
    at.number_input(key=_BASELOAD_GAIN).set_value(0.6)
    at = _run(at)
    raw = _raw_profile()
    assert raw["thermal"]["gross_floor_area_m2"] == 150.0
    assert raw["baseload_internal_gain_factor"] == 0.6
    # Turning the switch back off keeps the values in the file.
    at.checkbox(key=_SOLAR).set_value(False)
    at = _run(at)
    assert _raw_profile()["thermal"]["solar_gains"]["window_area_m2"]["s"] == 10.0
