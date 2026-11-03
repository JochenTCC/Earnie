"""House configurator: the „Haus Wärme“ form splits building demand and heating system.

The fixture house ``test_home`` has the thermal_annual consumer ``wp`` with its reference
system ``heating_test_home``. The generation fields (heat source, power, min-on time, storage,
rod) sit under the „Heizsystem“ heading and are saved into that catalog entry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_NOM = "test_home__hc_g0_nom_0"


def _read(env: str) -> dict:
    return json.loads(Path(os.environ[env]).read_text(encoding="utf-8"))


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


def _reference() -> dict:
    return next(
        e for e in _read("EARNIE_COMPONENTS_PATH")["heating_systems"] if e["id"] == "heating_test_home"
    )


def _session() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    return at


def test_form_shows_building_and_heating_system_sections() -> None:
    at = _session()
    texts = [m.value for m in at.markdown]
    assert "**Gebäude / Wärmebedarf**" in texts
    assert f"**Heizsystem (Referenzsystem: {_reference()['label']})**" in texts
    assert at.number_input(key=_NOM).label == "Nennleistung Wärmepumpe (kW, elektrisch)"


def test_nominal_power_is_saved_into_the_reference_system() -> None:
    at = _session()
    at.number_input(key=_NOM).set_value(2.5).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert _reference()["nominal_power_kw"] == 2.5
    profile = next(
        p for p in _read("EARNIE_HOUSE_PROFILES_PATH")["profiles"] if p["id"] == "test_home"
    )
    wp = next(c for c in profile["consumers"] if c["id"] == "wp")
    assert "nominal_power_kw" not in wp
    assert wp["heating_system_id"] == "heating_test_home"
