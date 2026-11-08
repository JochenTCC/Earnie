"""T1, T3, T4: Fail-safe-Werte im HA-YAML-Paket (``ui/ha_carrier_download.py``)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from house_config.profiles_store import clear_house_profiles_doc_cache
from runtime_store.shadow.errors import ConfigReadOnlyError
from tests.apptest.helpers import assert_clean, file_snapshot, messages
from ui.auto_persist import SHADOW_READONLY_CAPTION

_SCRIPT = Path(__file__).parent / "scripts" / "run_form_ha_fail_safe.py"
_TIMEOUT_S = 30.0
_LIMIT = "ess.test_battery.set_ess_discharge_power_limit"
_POWER = "ess.test_battery.set_ess_active_power"
_MODE = "ess.test_battery.set_ess_mode"


def _house_path() -> Path:
    return Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])


def _components_path() -> Path:
    return Path(os.environ["EARNIE_COMPONENTS_PATH"])


@pytest.fixture(autouse=True)
def _write_signals():
    """Battery with a limit, the active power and a mode; restored after the test."""
    path = _components_path()
    original = path.read_bytes()
    doc = json.loads(original.decode("utf-8"))
    doc["batteries"][0].setdefault("ehal_bindings", {}).update({_LIMIT: "", _POWER: "", _MODE: ""})
    path.write_text(json.dumps(doc), encoding="utf-8")
    house_before = _house_path().read_bytes()
    from house_config.components_store import clear_components_doc_cache

    clear_components_doc_cache()
    clear_house_profiles_doc_cache()
    yield
    path.write_bytes(original)
    _house_path().write_bytes(house_before)
    clear_components_doc_cache()
    clear_house_profiles_doc_cache()


def _run() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert_clean(at)
    return at


def _saved() -> dict | None:
    plant = json.loads(_house_path().read_text(encoding="utf-8")).get("plant") or {}
    return plant.get("ha_fail_safe_values")


def _field(at: AppTest, ehal_id: str):
    return at.number_input(key=f"ha_fail_safe__{ehal_id}")


def _save(at: AppTest) -> AppTest:
    return at.button[0].click().run(timeout=_TIMEOUT_S)


def test_t1_value_survives_save_and_new_session() -> None:
    at = _run()
    _field(at, _LIMIT).set_value(5000.0)

    at = _save(at)

    assert_clean(at)
    assert _saved() == {_LIMIT: 5000.0}
    assert messages(at)["success"]
    assert _field(_run(), _LIMIT).value == 5000.0


def test_t1_clearing_a_value_removes_it() -> None:
    at = _run()
    _field(at, _LIMIT).set_value(5000.0)
    at = _save(at)

    _field(at, _LIMIT).set_value(None)
    at = _save(at)

    assert_clean(at)
    assert _saved() is None
    assert _field(_run(), _LIMIT).value is None


def test_t4_unsaved_change_is_not_persisted() -> None:
    at = _run()
    before = file_snapshot(_house_path())

    _field(at, _LIMIT).set_value(5000.0)
    at.run(timeout=_TIMEOUT_S)

    assert file_snapshot(_house_path()) == before
    assert _field(_run(), _LIMIT).value is None


def test_only_signals_with_a_unit_get_a_field() -> None:
    at = _run()

    keys = {field.key for field in at.number_input}
    assert f"ha_fail_safe__{_LIMIT}" in keys
    assert f"ha_fail_safe__{_POWER}" in keys
    assert f"ha_fail_safe__{_MODE}" not in keys


def test_limits_cannot_go_negative_but_the_active_power_can() -> None:
    at = _run()

    assert _field(at, _LIMIT).min == 0.0
    assert _field(at, _POWER).min is None or _field(at, _POWER).min < 0.0


def test_saved_value_reaches_the_package_in_the_same_run(monkeypatch) -> None:
    built: list[dict] = []
    from ui import ha_carrier_download

    real = ha_carrier_download.build_carrier_yaml

    def spy(house, components, **kwargs):
        built.append((house.get("plant") or {}).get("ha_fail_safe_values"))
        return real(house, components, **kwargs)

    monkeypatch.setattr("ui.ha_carrier_download.build_carrier_yaml", spy)
    monkeypatch.setattr("ui.ha_carrier_download._default_host", lambda: "192.168.1.10")
    at = _run()
    _field(at, _LIMIT).set_value(5000.0)

    _save(at)

    assert built[-1] == {_LIMIT: 5000.0}


def test_t3_shadow_mode_disables_the_form(monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    before = file_snapshot(_house_path())

    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)

    assert_clean(at)
    assert _field(at, _LIMIT).disabled
    assert SHADOW_READONLY_CAPTION in messages(at)["caption"]
    assert file_snapshot(_house_path()) == before


def test_t3_read_only_write_error_is_a_hint_not_an_exception(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise ConfigReadOnlyError("config schreibgeschützt")

    monkeypatch.setattr("ui.house_config_io.save_house_profiles", refuse)
    at = _run()
    _field(at, _LIMIT).set_value(5000.0)

    at = _save(at)

    assert_clean(at)
    assert SHADOW_READONLY_CAPTION in messages(at)["caption"]
    assert not messages(at)["success"]


def test_stale_value_blocks_the_package_until_the_form_is_saved(monkeypatch) -> None:
    monkeypatch.setattr("ui.ha_carrier_download._default_host", lambda: "192.168.1.10")
    doc = json.loads(_house_path().read_text(encoding="utf-8"))
    doc.setdefault("plant", {})["ha_fail_safe_values"] = {"ess.gone.set_ess_active_power": 0.0}
    _house_path().write_text(json.dumps(doc), encoding="utf-8")
    clear_house_profiles_doc_cache()

    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)

    assert not at.exception
    assert any("ess.gone.set_ess_active_power" in text for text in messages(at)["error"])
    assert not at.get("download_button")

    at = _save(at)

    assert _saved() is None
    assert not messages(at)["error"]
    assert at.get("download_button")
