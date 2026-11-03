"""Hauskonfigurator (SUSI P6): „Personen im Haushalt“ next to the Jahresverbrauch.

The fixture house ``test_home`` (2 persons) has the heating consumer ``wp``. Below the
Jahresverbrauch the form compares the household electricity (Jahresverbrauch minus heating,
EV, pool) with the SUSI reference value and warns above ±40 %.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.apptest.helpers import assert_clean

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_PREFIX = "test_home__"
_PERSONS = f"{_PREFIX}house_persons"
_ANNUAL = f"{_PREFIX}house_annual_kwh"
_SWITCH = f"{_PREFIX}house_heating_enabled"


@pytest.fixture(autouse=True)
def _isolated(_isolated_backtesting_config):
    from house_config.components_store import clear_components_doc_cache
    from house_config.profiles_store import clear_house_profiles_doc_cache
    from tests.conftest import _reinit_config_offline

    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    house = json.loads(path.read_text(encoding="utf-8"))
    # Room for the baseload check, as in test_persist_consumers_apptest.
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


def _reference_line(at: AppTest) -> str:
    return next(c.value for c in at.caption if "Richtwert (SUSI" in c.value)


def _household_warnings(at: AppTest) -> list[str]:
    return [w.value for w in at.warning if "Richtwert" in w.value]


def _raw_profile() -> dict:
    doc = json.loads(Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"]).read_text(encoding="utf-8"))
    return next(p for p in doc["profiles"] if p["id"] == "test_home")


def test_reference_line_and_warning_follow_the_household_electricity() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    line = _reference_line(at)
    assert "Richtwert (SUSI, 2 Personen): 3400 kWh/a" in line
    assert "ohne Wärmepumpe" in line
    assert _household_warnings(at)  # 200000 kWh/a is far above the reference

    # The heat pump draw depends on the Jahresverbrauch (internal gains of the Grundlast,
    # SUSI P2), so the household share is set twice to settle.
    for _ in range(2):
        heating_kwh = float(re.search(r"ohne Wärmepumpe \((\d+) kWh/a\)", line).group(1))
        at.number_input(key=_ANNUAL).set_value(heating_kwh + 3400.0)
        at = _run(at)
        line = _reference_line(at)
    deviation = int(re.search(r"Abweichung ([+-]\d+) %", line).group(1))
    assert abs(deviation) <= 1, line
    assert not _household_warnings(at)


def test_persons_field_stays_with_heating_off() -> None:
    at = _run(AppTest.from_file(str(_SCRIPT)))
    at.checkbox(key=_SWITCH).set_value(False)
    at = _run(at)
    assert _PERSONS in {w.key for w in at.number_input}
    at.number_input(key=_PERSONS).set_value(1)
    at = _run(at)
    assert _raw_profile()["persons"] == 1
    line = _reference_line(at)
    assert "Richtwert (SUSI, 1 Person): 1700 kWh/a" in line
    # Heating off: the heating consumer is not planned, so nothing is subtracted.
    assert "ohne" not in line
    assert any("„Heizung betrachten“ ist aus" in c.value for c in at.caption)


def test_save_keeps_the_vat_flag() -> None:
    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    house = json.loads(path.read_text(encoding="utf-8"))
    house["profiles"][0]["vat_deductible"] = True
    path.write_text(json.dumps(house, ensure_ascii=False), encoding="utf-8")
    from house_config.profiles_store import clear_house_profiles_doc_cache

    clear_house_profiles_doc_cache()
    at = _run(AppTest.from_file(str(_SCRIPT)))
    at.number_input(key=_PERSONS).set_value(3)
    _run(at)
    raw = _raw_profile()
    assert raw["persons"] == 3
    assert raw["vat_deductible"] is True
