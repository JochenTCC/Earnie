"""House configurator: "Gemessener Heizstab-Verbrauch" on the thermal_annual consumer ``wp``.

The field is shown only when the reference system ``heating_test_home`` has a heat storage
and a heating rod part. It stores ``heating_rod_annual_kwh`` or ``heating_rod_profile_csv``
on the consumer (mutually exclusive, never in the heating-system catalog). Autosave like
the rest of the house profile.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from house_config.heating_systems import ROD_ANNUAL_KWH_KEY, ROD_PROFILE_CSV_KEY

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_KEY_PREFIX = "test_home__hc_g0_"
_MODE = _KEY_PREFIX + "rod_measured_mode_0"
_KWH = _KEY_PREFIX + "rod_measured_kwh_0"
_CSV = _KEY_PREFIX + "rod_measured_csv_0"
_ROD_USE = _KEY_PREFIX + "rod_use_0"
_NONE = "Keine Angabe"
_ANNUAL = "Jahresverbrauch (kWh)"
_FILE = "Eigene CSV-Datei"
_STORAGE = {"volume_liters": 300.0, "heat_loss_kw_per_k": 0.01, "setpoint_c": 50.0, "tolerance_c": 5.0}
_ROD = {"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}


def _read(env: str) -> dict:
    return json.loads(Path(os.environ[env]).read_text(encoding="utf-8"))


def _write(env: str, doc: dict) -> None:
    Path(os.environ[env]).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _setup(*, storage: bool, rod: bool, consumer_extra: dict | None = None) -> None:
    """Reference system with/without storage and rod; optional measured values on ``wp``."""
    from house_config.components_store import clear_components_doc_cache
    from house_config.profiles_store import clear_house_profiles_doc_cache
    from tests.conftest import _reinit_config_offline

    comp = _read("EARNIE_COMPONENTS_PATH")
    system = next(e for e in comp["heating_systems"] if e["id"] == "heating_test_home")
    if storage:
        system["heat_storage"] = dict(_STORAGE)
    if rod:
        system["parts"] = [dict(_ROD)]
    _write("EARNIE_COMPONENTS_PATH", comp)

    house = _read("EARNIE_HOUSE_PROFILES_PATH")
    # Room for the baseload check, as in test_persist_consumers_apptest.
    house["profiles"][0]["annual_kwh"] = 200000.0
    house["profiles"][0]["consumers"][0].update(consumer_extra or {})
    _write("EARNIE_HOUSE_PROFILES_PATH", house)
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()
    _reinit_config_offline()


@pytest.fixture(autouse=True)
def _isolated(_isolated_backtesting_config):
    # Explicit dependency: the tests write only after the conftest bound the env to tmp_path.
    yield


def _rod_csv(tmp_path: Path) -> str:
    """Canonical hourly profile over 12 whole months (the baseload check reads it)."""
    from datetime import datetime, timedelta

    start = datetime(2025, 1, 1)
    rows = [f"{(start + timedelta(hours=h)).isoformat()};0.05" for h in range(366 * 24)]
    path = tmp_path / "heizstab.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


def _wp() -> dict:
    profile = next(p for p in _read("EARNIE_HOUSE_PROFILES_PATH")["profiles"] if p["id"] == "test_home")
    return next(c for c in profile["consumers"] if c["id"] == "wp")


def _reference() -> dict:
    return next(e for e in _read("EARNIE_COMPONENTS_PATH")["heating_systems"] if e["id"] == "heating_test_home")


def _session() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    _assert_clean(at)
    return at


def _assert_clean(at: AppTest) -> None:
    assert not at.exception
    assert not at.error, [e.value for e in at.error]


def _has(at: AppTest, kind: str, key: str) -> bool:
    return any(w.key == key for w in getattr(at, kind))


def _pick(at: AppTest, mode: str) -> AppTest:
    at.selectbox(key=_MODE).set_value(mode).run(timeout=_TIMEOUT_S)
    _assert_clean(at)
    return at


@pytest.mark.parametrize(
    "storage,rod",
    [pytest.param(False, False, id="no-storage"), pytest.param(True, False, id="storage-without-rod")],
)
def test_field_hidden_without_heating_rod(storage: bool, rod: bool) -> None:
    _setup(storage=storage, rod=rod)
    at = _session()
    assert _has(at, "checkbox", _ROD_USE) is storage
    if storage:
        assert at.checkbox(key=_ROD_USE).value is False
    assert not _has(at, "selectbox", _MODE)
    assert ROD_ANNUAL_KWH_KEY not in _wp()
    assert ROD_PROFILE_CSV_KEY not in _wp()


def test_disabling_the_rod_hides_the_field_and_drops_the_value() -> None:
    _setup(storage=True, rod=True, consumer_extra={ROD_ANNUAL_KWH_KEY: 500.0})
    at = _session()
    assert at.selectbox(key=_MODE).value == _ANNUAL
    at.checkbox(key=_ROD_USE).uncheck().run(timeout=_TIMEOUT_S)
    _assert_clean(at)
    assert not _has(at, "selectbox", _MODE)
    assert "parts" not in _reference() or not _reference()["parts"]
    assert ROD_ANNUAL_KWH_KEY not in _wp()


def test_field_defaults_to_no_value_with_heating_rod() -> None:
    _setup(storage=True, rod=True)
    at = _session()
    assert at.checkbox(key=_ROD_USE).value is True
    assert at.selectbox(key=_MODE).value == _NONE
    assert at.selectbox(key=_MODE).options == [_NONE, _ANNUAL, _FILE]
    assert not _has(at, "number_input", _KWH)
    assert not _has(at, "text_input", _CSV)


def test_annual_kwh_is_saved_on_the_consumer_and_reseeded() -> None:
    _setup(storage=True, rod=True)
    at = _pick(_session(), _ANNUAL)
    assert at.number_input(key=_KWH).value == pytest.approx(100.0)
    at.number_input(key=_KWH).set_value(850.0).run(timeout=_TIMEOUT_S)
    _assert_clean(at)
    assert _wp()[ROD_ANNUAL_KWH_KEY] == pytest.approx(850.0)
    assert ROD_PROFILE_CSV_KEY not in _wp()
    assert ROD_ANNUAL_KWH_KEY not in _reference()

    # Rerun of the same session keeps the value; a new session seeds it from the file.
    at.run(timeout=_TIMEOUT_S)
    assert at.number_input(key=_KWH).value == pytest.approx(850.0)
    fresh = _session()
    assert fresh.selectbox(key=_MODE).value == _ANNUAL
    assert fresh.number_input(key=_KWH).value == pytest.approx(850.0)


def test_switching_from_csv_to_annual_removes_the_csv_key(tmp_path) -> None:
    csv_path = _rod_csv(tmp_path)
    _setup(storage=True, rod=True, consumer_extra={ROD_PROFILE_CSV_KEY: csv_path})
    at = _session()
    assert at.selectbox(key=_MODE).value == _FILE
    assert at.text_input(key=_CSV).value == csv_path
    _pick(at, _ANNUAL)
    assert _wp()[ROD_ANNUAL_KWH_KEY] == pytest.approx(100.0)
    assert ROD_PROFILE_CSV_KEY not in _wp()


def test_csv_path_is_saved_on_the_consumer_and_reseeded(tmp_path) -> None:
    csv_path = _rod_csv(tmp_path)
    _setup(storage=True, rod=True, consumer_extra={ROD_ANNUAL_KWH_KEY: 400.0})
    at = _pick(_session(), _FILE)
    assert at.text_input(key=_CSV).value == ""
    # Empty path stores nothing (and also no longer the annual value).
    assert ROD_PROFILE_CSV_KEY not in _wp()
    assert ROD_ANNUAL_KWH_KEY not in _wp()

    at.text_input(key=_CSV).set_value(f"  {csv_path}  ").run(timeout=_TIMEOUT_S)
    _assert_clean(at)
    assert _wp()[ROD_PROFILE_CSV_KEY] == csv_path
    assert ROD_ANNUAL_KWH_KEY not in _wp()
    assert ROD_PROFILE_CSV_KEY not in _reference()

    fresh = _session()
    assert fresh.selectbox(key=_MODE).value == _FILE
    assert fresh.text_input(key=_CSV).value == csv_path


@pytest.mark.parametrize("start", ["annual", "csv"])
def test_back_to_no_value_removes_both_keys(start: str, tmp_path) -> None:
    extra = {ROD_ANNUAL_KWH_KEY: 600.0} if start == "annual" else {ROD_PROFILE_CSV_KEY: _rod_csv(tmp_path)}
    _setup(storage=True, rod=True, consumer_extra=extra)
    at = _pick(_session(), _NONE)
    assert not _has(at, "number_input", _KWH)
    assert not _has(at, "text_input", _CSV)
    assert ROD_ANNUAL_KWH_KEY not in _wp()
    assert ROD_PROFILE_CSV_KEY not in _wp()
    assert _session().selectbox(key=_MODE).value == _NONE
