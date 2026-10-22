"""Ebene 1, Muster C (``st.form`` + Submit) und D (Schreiben beim Umschalten).

C: OpenEMS-Verbindung, Home-Assistant-Auswahl, Loxone-Zugangsdaten (.env),
Gerätestern-Schwellen. Hier ist T4 echt relevant: Änderungen ohne Submit dürfen
nichts schreiben. D: Silent-Schalter im Optimierer-Dienst.

Es werden ausschließlich Testwerte verwendet. ``.env`` und ``config.json`` liegen
dank der autouse-Fixture in ``conftest.py`` unter ``tmp_path``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_SCRIPTS = Path(__file__).parent / "scripts"
_TIMEOUT_S = 20.0


def _run(script: str) -> AppTest:
    return AppTest.from_file(str(_SCRIPTS / script)).run(timeout=_TIMEOUT_S)


def _config_path() -> Path:
    return Path(os.environ["EARNIE_CONFIG_PATH"])


def _config() -> dict:
    return json.loads(_config_path().read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# OpenEMS-Verbindung (config.json -> ehal.openems)
# --------------------------------------------------------------------------

_OPENEMS_VALUES = {
    "base_url": "http://openems-test:8085",
    "username": "tester-ünï",
    "password": "test-passwort",
    "ess_component": "ess7",
    "evcs_component": "evcs3",
    "adapter_id": "openems_test",
}


def _fill_openems(at: AppTest, values: dict) -> None:
    for name, value in values.items():
        at.text_input(key=f"t_openems_{name}").set_value(value)


def test_openems_t1_submit_persists_all_fields_and_survives_new_session() -> None:
    at = _run("run_form_openems.py")
    _fill_openems(at, _OPENEMS_VALUES)
    at.button(key="t_openems_submit").click().run(timeout=_TIMEOUT_S)
    assert not at.exception

    ehal = _config()["ehal"]
    assert ehal["backend"] == "openems"
    assert ehal["adapter_id"] == _OPENEMS_VALUES["adapter_id"]
    for name in ("base_url", "username", "password", "ess_component", "evcs_component"):
        assert ehal["openems"][name] == _OPENEMS_VALUES[name], name

    fresh = _run("run_form_openems.py")
    for name, value in _OPENEMS_VALUES.items():
        assert fresh.text_input(key=f"t_openems_{name}").value == value, name


def test_openems_t3_empty_base_url_is_rejected_and_config_stays_unchanged() -> None:
    before = _config_path().read_bytes()
    at = _run("run_form_openems.py")
    _fill_openems(at, {**_OPENEMS_VALUES, "base_url": ""})
    at.button(key="t_openems_submit").click().run(timeout=_TIMEOUT_S)

    assert not at.exception
    assert [e.value for e in at.error] == ["Base-URL ist erforderlich."]
    assert _config_path().read_bytes() == before


def test_openems_t4_changes_without_submit_are_not_persisted() -> None:
    before = _config_path().read_bytes()
    at = _run("run_form_openems.py")
    _fill_openems(at, _OPENEMS_VALUES)
    at.run(timeout=_TIMEOUT_S)  # Rerun ohne Submit
    assert _config_path().read_bytes() == before

    fresh = _run("run_form_openems.py")
    assert fresh.text_input(key="t_openems_base_url").value == "http://openems-edge:8084"


# --------------------------------------------------------------------------
# Home-Assistant-Auswahl (config.json -> ehal.backend / adapter_id)
# --------------------------------------------------------------------------

def test_ha_t1_submit_persists_backend_and_adapter_id() -> None:
    at = _run("run_form_ha.py")
    at.text_input(key="t_ha_adapter_id").set_value("ha_test")
    at.button(key="t_ha_submit").click().run(timeout=_TIMEOUT_S)
    assert not at.exception

    ehal = _config()["ehal"]
    assert ehal["backend"] == "ha"
    assert ehal["adapter_id"] == "ha_test"
    assert _run("run_form_ha.py").text_input(key="t_ha_adapter_id").value == "ha_test"


def test_ha_t4_adapter_id_without_submit_is_not_persisted() -> None:
    before = _config_path().read_bytes()
    at = _run("run_form_ha.py")
    at.text_input(key="t_ha_adapter_id").set_value("ha_nicht_gespeichert").run(timeout=_TIMEOUT_S)
    assert _config_path().read_bytes() == before


# --------------------------------------------------------------------------
# Loxone-Zugangsdaten (.env)
# --------------------------------------------------------------------------

def _dotenv_path() -> Path:
    return Path(os.environ["EARNIE_DOTENV_PATH"])


def test_loxone_t1_submit_writes_dotenv_and_new_session_shows_values(monkeypatch) -> None:
    at = _run("run_form_loxone.py")
    at.text_input(key="t_loxone_ip").set_value("192.168.178.77")
    at.text_input(key="t_loxone_user").set_value("testuser")
    at.text_input(key="t_loxone_password").set_value("testpass-123")
    at.button(key="t_loxone_submit").click().run(timeout=_TIMEOUT_S)
    assert not at.exception

    content = _dotenv_path().read_text(encoding="utf-8")
    assert "LOXONE_IP=192.168.178.77" in content
    assert "testuser" in content and "testpass-123" in content

    fresh = _run("run_form_loxone.py")
    assert fresh.text_input(key="t_loxone_ip").value == "192.168.178.77"
    assert fresh.text_input(key="t_loxone_user").value == "testuser"


@pytest.mark.parametrize("bad_ip", ["", "999.1.1.1", "kein-host", "192.168.1"])
def test_loxone_t3_invalid_ip_is_rejected_and_no_dotenv_is_written(bad_ip: str) -> None:
    at = _run("run_form_loxone.py")
    at.text_input(key="t_loxone_ip").set_value(bad_ip)
    at.text_input(key="t_loxone_user").set_value("testuser")
    at.text_input(key="t_loxone_password").set_value("testpass-123")
    at.button(key="t_loxone_submit").click().run(timeout=_TIMEOUT_S)

    assert not at.exception
    assert at.error, "Ungültige IP muss als Fehlermeldung sichtbar sein"
    assert not _dotenv_path().exists()


def test_loxone_t4_values_without_submit_are_not_written() -> None:
    at = _run("run_form_loxone.py")
    at.text_input(key="t_loxone_ip").set_value("192.168.178.77")
    at.run(timeout=_TIMEOUT_S)
    assert not _dotenv_path().exists()


# --------------------------------------------------------------------------
# Gerätestern-Schwellen (config.json -> appliance_recommendation)
# --------------------------------------------------------------------------

_DEVICES_SCRIPT = "run_form_star_thresholds.py"


def test_devices_stars_t1_submit_persists_thresholds() -> None:
    at = _run(_DEVICES_SCRIPT)
    at.number_input(key="devices_star_abs_margin_cent").set_value(1.25)
    at.number_input(key="devices_star_pct_stars_4").set_value(7.5)
    at.number_input(key="devices_star_pct_stars_1").set_value(40.0)
    at.button(key="devices_star_save").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert [s.value for s in at.success] == ["Sterne-Schwellen gespeichert."]

    stored = _config()["appliance_recommendation"]
    assert stored["abs_margin_cent"] == 1.25
    assert stored["pct_stars_4"] == 7.5
    assert stored["pct_stars_1"] == 40.0

    fresh = _run(_DEVICES_SCRIPT)
    assert fresh.number_input(key="devices_star_abs_margin_cent").value == 1.25
    assert fresh.number_input(key="devices_star_pct_stars_4").value == 7.5
    assert fresh.number_input(key="devices_star_pct_stars_1").value == 40.0


def test_devices_stars_t4_changes_without_submit_are_not_persisted() -> None:
    before = _config_path().read_bytes()
    at = _run(_DEVICES_SCRIPT)
    at.number_input(key="devices_star_pct_stars_4").set_value(9.0).run(timeout=_TIMEOUT_S)
    assert _config_path().read_bytes() == before


# --------------------------------------------------------------------------
# Muster D: Silent-Schalter (local_settings.json)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("target", [False, True])
def test_silent_toggle_writes_local_settings_and_new_session_shows_it(
    local_settings: Path, target: bool
) -> None:
    at = _run("run_page_daemon.py")
    toggle = at.toggle(key="daemon_silent_mode")
    if toggle.value is target:  # Ausgangszustand umgehen: erst auf das Gegenteil
        toggle.set_value(not target).run(timeout=_TIMEOUT_S)
        toggle = at.toggle(key="daemon_silent_mode")
    toggle.set_value(target).run(timeout=_TIMEOUT_S)
    assert not at.exception

    assert json.loads(local_settings.read_text(encoding="utf-8"))["silent_mode"] is target
    assert _run("run_page_daemon.py").toggle(key="daemon_silent_mode").value is target


def test_silent_toggle_is_locked_in_shadow_mode_and_writes_nothing(
    local_settings: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    at = _run("run_page_daemon.py")
    assert at.toggle(key="daemon_silent_mode").disabled
    assert not local_settings.exists()


# --------------------------------------------------------------------------
# L3: Erfolgsmeldung direkt vor st.rerun() (Verdacht aus der Bestandsaufnahme)
# --------------------------------------------------------------------------
# Bekannter Fehler: ``st.success(...)`` steht unmittelbar vor ``st.rerun()``; der Rerun
# verwirft die Ausgabe, der Nutzer sieht keine Bestätigung. Die Daten sind gespeichert
# (Tests oben). Fix: Flash-Meldung über den Rerun hinweg (siehe ``ui/auto_persist.py``).
_SWALLOWED = pytest.mark.xfail(
    strict=True,
    reason="st.success vor st.rerun(): Bestätigung wird verworfen (Backlog-Bugfixes)",
)


def _texts(elements) -> str:
    return " | ".join(e.value for e in elements)


@_SWALLOWED
def test_l3_openems_save_confirmation_is_visible() -> None:
    at = _run("run_form_openems.py")
    _fill_openems(at, _OPENEMS_VALUES)
    at.button(key="t_openems_submit").click().run(timeout=_TIMEOUT_S)
    assert "OpenEMS-Zugang gespeichert" in _texts(at.success)


@_SWALLOWED
def test_l3_ha_save_confirmation_is_visible() -> None:
    at = _run("run_form_ha.py")
    at.button(key="t_ha_submit").click().run(timeout=_TIMEOUT_S)
    assert "Home Assistant gewählt" in _texts(at.success)


@_SWALLOWED
def test_l3_loxone_save_confirmation_is_visible() -> None:
    at = _run("run_form_loxone.py")
    at.text_input(key="t_loxone_ip").set_value("192.168.178.77")
    at.text_input(key="t_loxone_user").set_value("testuser")
    at.text_input(key="t_loxone_password").set_value("testpass-123")
    at.button(key="t_loxone_submit").click().run(timeout=_TIMEOUT_S)
    assert "Zugangsdaten gespeichert" in _texts(at.success)


@_SWALLOWED
def test_l3_silent_toggle_confirmation_is_visible(local_settings: Path) -> None:
    at = _run("run_page_daemon.py")
    toggle = at.toggle(key="daemon_silent_mode")
    toggle.set_value(not toggle.value).run(timeout=_TIMEOUT_S)
    shown = _texts(at.success) + " | " + _texts(at.warning)
    assert "Silent-Modus aktiv" in shown or "Loud" in shown
