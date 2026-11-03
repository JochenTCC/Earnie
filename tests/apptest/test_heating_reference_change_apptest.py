"""House configurator: warning before a change of the reference system's heat-source type.

The fixture house ``test_home`` has the thermal_annual consumer ``wp`` with its reference
system ``heating_test_home`` (air heat pump). A change of the heat-source type holds the
auto-save until the user picks one of the two choices; heat-pump type and parameter
corrections save without a warning.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_SOURCE = "test_home__hc_g0_heat_source_0"
_WP_TYPE = "test_home__hc_g0_wp_0"
_POWER = "test_home__hc_g0_heat_power_0"
_ANNUAL = "test_home__house_annual_kwh"


def _read(env: str) -> dict:
    return json.loads(Path(os.environ[env]).read_text(encoding="utf-8"))


def _house() -> dict:
    return next(
        p for p in _read("EARNIE_HOUSE_PROFILES_PATH")["profiles"] if p["id"] == "test_home"
    )


def _reference() -> dict:
    return next(
        e for e in _read("EARNIE_COMPONENTS_PATH")["heating_systems"] if e["id"] == "heating_test_home"
    )


def _write_house(**fields) -> None:
    from house_config.profiles_store import clear_house_profiles_doc_cache

    path = Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["profiles"][0].update(fields)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    clear_house_profiles_doc_cache()


@pytest.fixture(autouse=True)
def _isolated(_isolated_backtesting_config):
    from house_config.components_store import clear_components_doc_cache
    from tests.conftest import _reinit_config_offline

    # Room for the baseload check, as in test_heating_form_split_apptest.
    _write_house(annual_kwh=200000.0)
    clear_components_doc_cache()
    _reinit_config_offline()
    yield


def _session() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    return at


def _warnings(at: AppTest) -> list[str]:
    return [w.value for w in at.warning if "Heizsystem geändert" in w.value]


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def _labels(at: AppTest) -> set[str]:
    return {b.label for b in at.button}


def _to_gas(at: AppTest) -> AppTest:
    at.selectbox(key=_SOURCE).set_value("gas").run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def test_annual_kwh_only_warns_with_adjust_or_keep() -> None:
    at = _to_gas(_session())
    warnings = _warnings(at)
    assert len(warnings) == 1 and "Jahresverbrauch" in warnings[0]
    assert {"Zu Gas wechseln", "Bei Wärmepumpe bleiben"} <= _labels(at)
    assert "Messdaten entfernen und zu Gas wechseln" not in _labels(at)
    assert _reference()["heat_source"]["type"] == "heat_pump"  # held

    at.number_input(key=_ANNUAL).set_value(150000.0).run(timeout=_TIMEOUT_S)
    assert _reference()["heat_source"]["type"] == "heat_pump"  # still held
    _button(at, "Zu Gas wechseln").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert _reference()["heat_source"] == {"type": "gas"}
    assert _house()["annual_kwh"] == 150000.0
    assert not _warnings(at)


def test_keep_restores_the_saved_heating_system() -> None:
    at = _to_gas(_session())
    _button(at, "Bei Wärmepumpe bleiben").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not _warnings(at)
    assert at.selectbox(key=_SOURCE).value == "heat_pump"
    assert _reference()["heat_source"]["type"] == "heat_pump"
    # The value is sent to the browser (set_value); a popped key left it showing the new type.
    assert at.selectbox(key=_SOURCE).proto.set_value


def test_keep_after_gas_to_heat_pump_restores_gas() -> None:
    _write_reference(heat_source={"type": "gas"})
    at = _session()
    at.selectbox(key=_SOURCE).set_value("heat_pump").run(timeout=_TIMEOUT_S)
    assert _warnings(at)
    assert {"Zu Wärmepumpe wechseln", "Bei Gas bleiben"} <= _labels(at)
    _button(at, "Bei Gas bleiben").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not _warnings(at)
    assert at.selectbox(key=_SOURCE).value == "gas"
    assert at.selectbox(key=_SOURCE).proto.set_value
    assert not [s for s in at.selectbox if s.key == _WP_TYPE]
    assert _reference()["heat_source"] == {"type": "gas"}


def test_measured_csv_warns_with_remove_or_keep(tmp_path) -> None:
    csv_path = tmp_path / "total.csv"
    rows = [f"2024-01-01 {h:02d}:00:00;1.5" for h in range(24)]
    csv_path.write_text("timestamp;power_kw\n" + "\n".join(rows) + "\n", encoding="utf-8")
    _write_house(total_profile_csv=str(csv_path))
    at = _to_gas(_session())
    warnings = _warnings(at)
    assert len(warnings) == 1 and "CSV-Messdaten" in warnings[0]
    assert {"Messdaten entfernen und zu Gas wechseln", "Bei Wärmepumpe bleiben"} <= _labels(at)
    assert "Zu Gas wechseln" not in _labels(at)
    assert _reference()["heat_source"]["type"] == "heat_pump"

    _button(at, "Messdaten entfernen und zu Gas wechseln").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert _reference()["heat_source"] == {"type": "gas"}
    assert not _house().get("total_profile_csv")
    assert not _warnings(at)


def _write_reference(**fields) -> None:
    from house_config.components_store import clear_components_doc_cache

    path = Path(os.environ["EARNIE_COMPONENTS_PATH"])
    doc = json.loads(path.read_text(encoding="utf-8"))
    entry = next(e for e in doc["heating_systems"] if e["id"] == "heating_test_home")
    entry.update(fields)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    clear_components_doc_cache()


def test_gas_to_heat_pump_with_csv_warns(tmp_path) -> None:
    csv_path = tmp_path / "total.csv"
    rows = [f"2024-01-01 {h:02d}:00:00;1.5" for h in range(24)]
    csv_path.write_text("timestamp;power_kw\n" + "\n".join(rows) + "\n", encoding="utf-8")
    _write_house(total_profile_csv=str(csv_path))
    _write_reference(heat_source={"type": "gas"})
    at = _session()
    assert at.selectbox(key=_SOURCE).value == "gas"
    at.selectbox(key=_SOURCE).set_value("heat_pump").run(timeout=_TIMEOUT_S)
    assert not at.exception
    warnings = _warnings(at)
    assert len(warnings) == 1 and "CSV-Messdaten" in warnings[0]
    assert _reference()["heat_source"]["type"] == "gas"  # held
    # Shown in the consumer's expander under the heat-source select box, not at the page end.
    in_expanders = [
        w.value for exp in at.expander for w in exp.warning if "Heizsystem geändert" in w.value
    ]
    assert in_expanders == warnings


def test_heat_pump_type_and_parameters_save_without_warning() -> None:
    at = _session()
    at.selectbox(key=_WP_TYPE).set_value("erde").run(timeout=_TIMEOUT_S)
    at.number_input(key=_POWER).set_value(8.75).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not _warnings(at)
    reference = _reference()
    assert reference["heat_source"]["heat_pump_type"] == "erde"
    assert reference["heating_power_kw"] == 8.75


def test_change_reverted_before_saving_is_no_change() -> None:
    at = _to_gas(_session())
    assert _warnings(at)
    at.selectbox(key=_SOURCE).set_value("heat_pump").run(timeout=_TIMEOUT_S)
    at.number_input(key=_POWER).set_value(8.75).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not _warnings(at)
    reference = _reference()
    assert reference["heat_source"]["type"] == "heat_pump"
    assert reference["heating_power_kw"] == 8.75
