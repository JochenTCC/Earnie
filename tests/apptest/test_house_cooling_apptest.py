"""Hauskonfigurator: section „Kühlung“ with the switch „Kühlung betrachten“.

The fixture house ``test_home`` has heating on and a „Haus Wärme“ consumer, so the switch is
available. Turning it on shows the device fields; every change is auto-saved into
``house_profiles.json`` (``cooling_enabled`` on the profile, ``cooling`` on the heating consumer).
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
_ENABLED = f"{_PREFIX}house_cooling_enabled"
_POWER = f"{_PREFIX}house_cooling_power"
_SEER_SPLIT = f"{_PREFIX}house_cooling_seer_split"


@pytest.fixture(autouse=True)
def _isolated(_isolated_backtesting_config, monkeypatch):
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
    # The offline climate has no hourly archive: a fixed cooling year (8 h × 0.5 kW).
    year = [0.0] * 8760
    for hour in range(5000, 5008):
        year[hour] = 0.5
    monkeypatch.setattr(
        "optimizer.house_cooling._reference_year_hourly_kw", lambda _c, _p: list(year)
    )
    yield


def _run(at: AppTest) -> AppTest:
    at.run(timeout=_TIMEOUT_S)
    assert_clean(at)
    assert not at.error, [e.value for e in at.error]
    return at


def _raw_profile() -> dict:
    doc = json.loads(Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"]).read_text(encoding="utf-8"))
    return next(p for p in doc["profiles"] if p["id"] == "test_home")


def _heating_consumer(raw: dict) -> dict:
    return next(c for c in raw["consumers"] if c["type"] == "thermal_annual")


def test_cooling_switch_shows_device_and_saves_it() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    assert at.checkbox(key=_ENABLED).value is False
    assert _POWER not in {w.key for w in at.number_input}
    at.checkbox(key=_ENABLED).set_value(True)
    at = _run(at)
    assert at.number_input(key=_SEER_SPLIT).value == 5.0
    assert any("Klimaanlage im Hausmodell: 4 kWh/a" in c.value for c in at.caption)
    at.number_input(key=_POWER).set_value(5.0)
    at = _run(at)
    raw = _raw_profile()
    assert raw["cooling_enabled"] is True
    assert _heating_consumer(raw)["cooling"] == {
        "type": "split",
        "seer": 5.0,
        "cooling_power_kw": 5.0,
        "setpoint_c": 26.0,
    }
    # Switch off: the device stays stored.
    at.checkbox(key=_ENABLED).set_value(False)
    at = _run(at)
    raw = _raw_profile()
    assert raw["cooling_enabled"] is False
    assert _heating_consumer(raw)["cooling"]["cooling_power_kw"] == 5.0


def test_appliance_kind_field_is_gone() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    assert not [w for w in at.selectbox if "hc_appliance_kind" in str(w.key)]
