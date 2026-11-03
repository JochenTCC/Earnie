"""House configurator: building demand at house level, heating system in „Haus Wärme“.

The fixture house ``test_home`` has the thermal_annual consumer ``wp`` with its reference
system ``heating_test_home``. The building fields sit in the house section „Gebäude /
Wärmebedarf“; the generation fields (heat source, power, min-on time, storage, rod) sit under
the „Heizsystem“ heading of the consumer and are saved into that catalog entry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_POWER = "test_home__hc_g0_heat_power_0"


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
    assert "Gebäude / Wärmebedarf" in [h.value for h in at.subheader]
    texts = [m.value for m in at.markdown]
    assert "**Gebäude / Wärmebedarf**" not in texts
    assert f"**Heizsystem (Referenzsystem: {_reference()['label']})**" in texts
    # The consumer form has no building fields of its own.
    keys = {w.key for w in at.number_input}
    assert "test_home__house_thermal_area" in keys
    assert not any(k.endswith("_area_0") and "solar" not in k for k in keys)
    assert at.number_input(key=_POWER).label == "Heizleistung (kW, thermisch)"


_HEAT_METRIC = "Geschätzter Wärmebedarf (kWh_th/a)"


def _metrics(at: AppTest) -> dict[str, float]:
    """Heating metrics of the „Haus Wärme“ form (the page shows other metrics too)."""
    labels = [m.label for m in at.metric]
    start = labels.index(_HEAT_METRIC)
    return {m.label: float(m.value) for m in list(at.metric)[start : start + 2]}


def test_heat_demand_kwh_th_is_the_main_figure() -> None:
    at = _session()
    assert list(_metrics(at)) == [
        _HEAT_METRIC,
        "Strombedarf mit diesem Heizsystem (kWh/a)",
    ]
    metrics = _metrics(at)
    heat = metrics["Geschätzter Wärmebedarf (kWh_th/a)"]
    electric = metrics["Strombedarf mit diesem Heizsystem (kWh/a)"]
    assert heat > 0.0
    # Heat pump luft, default JAZ 3.5: electricity = heat / JAZ.
    assert electric == pytest.approx(heat / 3.5, abs=1.0)


def test_heat_demand_stays_with_a_fuel_source() -> None:
    at = _session()
    heat_pump = _metrics(at)["Geschätzter Wärmebedarf (kWh_th/a)"]
    at.selectbox(key="test_home__hc_g0_heat_source_0").set_value("gas").run(timeout=_TIMEOUT_S)
    assert not at.exception
    metrics = _metrics(at)
    assert "Strombedarf mit diesem Heizsystem (kWh/a)" not in metrics
    fuel = metrics["Brennstoffbedarf mit diesem Heizsystem (kWh/a Endenergie)"]
    heat = metrics["Geschätzter Wärmebedarf (kWh_th/a)"]
    # Same heating power and no storage: the delivered heat does not depend on the source.
    assert heat == pytest.approx(heat_pump, abs=1.0)
    # Gas, default Nutzungsgrad 0.95: fuel = heat / 0.95.
    assert fuel == pytest.approx(heat / 0.95, abs=1.0)


def test_heating_power_is_saved_into_the_reference_system() -> None:
    at = _session()
    at.number_input(key=_POWER).set_value(8.75).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert _reference()["heating_power_kw"] == 8.75
    assert "nominal_power_kw" not in _reference()
    profile = next(
        p for p in _read("EARNIE_HOUSE_PROFILES_PATH")["profiles"] if p["id"] == "test_home"
    )
    wp = next(c for c in profile["consumers"] if c["id"] == "wp")
    assert "nominal_power_kw" not in wp
    assert wp["heating_system_id"] == "heating_test_home"
