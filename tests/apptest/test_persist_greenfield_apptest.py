"""Ebene 1 (T1, T3, T5, L3): Loxone-Import (Greenfield) in Smarthome-Backend.

``ui/ehal_greenfield_import.py::render_greenfield_import_section``: Der Button liest
``LoxAPP3.json`` (hier die Datei ``tests/fixtures/loxapp3_greenfield.json`` statt eines
Miniservers), setzt ``ehal.backend`` in ``config.json`` und schreibt Verbraucher und Bindings
in ``house_profiles.json``. Es gibt keinen Netzwerkzugriff.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from integrations.loxone_structure import LoxoneStructureError
from tests.apptest.helpers import assert_clean, file_snapshot, messages

_SCRIPT = Path(__file__).parent / "scripts" / "run_form_greenfield.py"
_FIXTURE = Path(__file__).parents[1] / "fixtures" / "loxapp3_greenfield.json"
_TIMEOUT_S = 60.0
_BUTTON = "hk_loxone_import_btn"
_DISMISS = "hk_greenfield_no"
_FLASH_FRAGMENT = "Loxone-Import gespeichert"


@pytest.fixture
def loxapp3(monkeypatch):
    """LoxAPP3 aus der Fixture-Datei; ``calls`` zählt die Abrufe."""
    doc = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    calls: list[dict] = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return doc

    monkeypatch.setattr("ui.ehal_greenfield_import.fetch_loxapp3_json", fake_fetch)
    return calls


@pytest.fixture
def loxone_credentials(monkeypatch):
    """Zugangsdaten in der Konfiguration (Testwerte); der Zugriffstest ist freigegeben."""
    from tests.conftest import _reinit_config_offline

    monkeypatch.setenv("LOXONE_IP", "10.0.0.2")
    monkeypatch.setenv("LOXONE_USER", "testuser")
    monkeypatch.setenv("LOXONE_PASS", "testpass")
    _reinit_config_offline()
    monkeypatch.setattr("ui.ehal_greenfield_import._loxone_import_access", lambda: (True, None))


def _run() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert_clean(at)
    return at


def _click(at: AppTest, key: str = _BUTTON) -> AppTest:
    return at.button(key=key).click().run(timeout=_TIMEOUT_S)


def _paths() -> tuple[Path, Path]:
    return Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"]), Path(os.environ["EARNIE_CONFIG_PATH"])


def _consumer_ids() -> set[str]:
    house, _config = _paths()
    profiles = json.loads(house.read_text(encoding="utf-8"))["profiles"]
    return {c["id"] for p in profiles for c in p["consumers"]}


def _backend() -> str | None:
    _house, config = _paths()
    return (json.loads(config.read_text(encoding="utf-8")).get("ehal") or {}).get("backend")


def _snapshots() -> tuple[bytes | None, bytes | None]:
    house, config = _paths()
    return file_snapshot(house), file_snapshot(config)


# --- Zugriffstest steuert den Button -----------------------------------------------------


def test_button_is_disabled_with_hint_without_credentials(loxapp3) -> None:
    at = _run()

    assert at.button(key=_BUTTON).disabled
    assert any("Zugangsdaten fehlen" in w for w in messages(at)["warning"])
    assert loxapp3 == []


@pytest.mark.parametrize(
    "result,enabled",
    [((True, None), True), ((False, "Miniserver nicht erreichbar."), False)],
)
def test_button_follows_access_check(monkeypatch, loxapp3, result, enabled) -> None:
    monkeypatch.setattr("ui.ehal_greenfield_import._loxone_import_access", lambda: result)

    at = _run()

    assert at.button(key=_BUTTON).disabled is not enabled
    assert bool(messages(at)["warning"]) is (not enabled)


def test_access_check_is_cached_per_credentials(monkeypatch, loxapp3) -> None:
    from tests.conftest import _reinit_config_offline

    probes: list[str] = []

    def fake_resolve(*, host, user, password, credentials_ok, **_kwargs):
        probes.append(f"{host}|{user}")
        return True, None

    monkeypatch.setattr("ui.ehal_greenfield_import.resolve_loxone_import_access", fake_resolve)
    monkeypatch.setattr("ui.ehal_greenfield_import.loxone_env_configured", lambda: True)
    monkeypatch.setenv("LOXONE_IP", "10.0.0.2")
    monkeypatch.setenv("LOXONE_USER", "testuser")
    monkeypatch.setenv("LOXONE_PASS", "testpass")
    _reinit_config_offline()

    at = _run()
    at.run(timeout=_TIMEOUT_S)
    assert probes == ["10.0.0.2|testuser"]  # zweiter Lauf: aus dem Session-State

    monkeypatch.setenv("LOXONE_IP", "10.0.0.3")
    _reinit_config_offline()
    at.run(timeout=_TIMEOUT_S)
    assert probes == ["10.0.0.2|testuser", "10.0.0.3|testuser"]


# --- Import: Erfolg ----------------------------------------------------------------------


def test_import_writes_consumers_and_backend_and_survives_new_session(
    loxone_credentials, loxapp3
) -> None:
    before = _consumer_ids()
    assert "waschmaschine" not in before
    at = _run()

    at = _click(at)

    assert_clean(at)
    assert not at.error
    assert len(loxapp3) == 1 and loxapp3[0]["host"] == "10.0.0.2"
    assert {"waschmaschine", "trockner", "e_auto"} <= _consumer_ids()
    assert before <= _consumer_ids()  # vorhandene Verbraucher bleiben
    assert _backend() == "loxone"
    fresh = _run()
    assert not fresh.success and "Treffer" not in " ".join(messages(fresh)["caption"])


def test_l3_success_message_and_report_are_visible_once_after_import(
    loxone_credentials, loxapp3
) -> None:
    at = _click(_run())

    assert any(_FLASH_FRAGMENT in text for text in messages(at)["success"])
    assert any("Treffer: " in text and "Verbraucher angelegt" in text for text in messages(at)["caption"])

    at.run(timeout=_TIMEOUT_S)  # nächster Lauf: Meldung weg, Bericht bleibt in der Session
    assert not at.success
    assert any("Treffer: " in text for text in messages(at)["caption"])


def test_import_selects_the_imported_profile_in_house_config(loxone_credentials, loxapp3) -> None:
    at = _click(_run())

    assert at.session_state["house_profile_select_pending"] == "test_home"


def test_second_import_changes_nothing(loxone_credentials, loxapp3) -> None:
    at = _click(_run())
    after_first = _snapshots()

    at = _click(at)

    assert_clean(at)
    assert _snapshots() == after_first


# --- Import: Fehlerpfade (T3) ------------------------------------------------------------


def test_t3_click_without_credentials_shows_error_and_writes_nothing(monkeypatch, loxapp3) -> None:
    monkeypatch.setattr("ui.ehal_greenfield_import._loxone_import_access", lambda: (True, None))
    at = _run()
    before = _snapshots()

    at = _click(at)

    assert_clean(at)
    assert messages(at)["error"] == ["Loxone-Zugangsdaten fehlen (LOXONE_IP / LOXONE_USER in .env)."]
    assert _snapshots() == before
    assert loxapp3 == []


def test_t3_unreachable_miniserver_shows_error_and_writes_nothing(
    loxone_credentials, monkeypatch
) -> None:
    def failing_fetch(**_kwargs):
        raise LoxoneStructureError("boom")

    monkeypatch.setattr("ui.ehal_greenfield_import.fetch_loxapp3_json", failing_fetch)
    at = _run()
    before = _snapshots()

    at = _click(at)

    assert_clean(at)
    assert messages(at)["error"] == ["LoxAPP3 konnte nicht geladen werden: boom"]
    assert _snapshots() == before
    assert _backend() != "loxone"


def test_t5_failing_import_leaves_config_untouched_and_shows_error(
    loxone_credentials, loxapp3, monkeypatch
) -> None:
    def failing_import(*_args, **_kwargs):
        raise ValueError("kaputt")

    monkeypatch.setattr("ui.ehal_greenfield_import.run_greenfield_import", failing_import)
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    before = _snapshots()

    at = _click(at)

    assert_clean(at)
    assert messages(at)["error"]
    assert _snapshots() == before


# --- Erstsetup-Hinweis -------------------------------------------------------------------


@pytest.fixture
def onboarding(monkeypatch):
    monkeypatch.setattr("ui.setup_readiness.needs_planning_onboarding", lambda: True)


def test_dismiss_button_only_in_first_setup() -> None:
    assert _DISMISS not in {b.key for b in _run().button}


def test_first_setup_offers_dismiss_and_dismiss_hides_it(onboarding, loxapp3) -> None:
    at = _run()
    assert _DISMISS in {b.key for b in at.button}
    assert at.button(key=_BUTTON).proto.type == "primary"

    at = _click(at, _DISMISS)

    assert_clean(at)
    assert _DISMISS not in {b.key for b in at.button}
    assert at.button(key=_BUTTON).proto.type == "secondary"
    assert loxapp3 == []


def test_first_setup_import_completes_the_wizard(onboarding, loxone_credentials, loxapp3) -> None:
    at = _click(_run())

    assert_clean(at)
    assert any(_FLASH_FRAGMENT in text for text in messages(at)["success"])
    assert _DISMISS not in {b.key for b in at.button}
    assert at.button(key=_BUTTON).proto.type == "secondary"


# --- Import ohne Hausprofil: Netzbereich ist Pflicht (Datenmodell 5) ---------------------

_GRID_AREA = "hk_loxone_import_grid_area"


@pytest.fixture
def no_house_profile():
    """Leeres house_profiles.json wie bei einer Neuinstallation: der Import legt ``live`` an."""
    house, _config = _paths()
    scenarios = Path(os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"])
    originals = {path: path.read_bytes() for path in (house, scenarios)}
    doc = json.loads(scenarios.read_text(encoding="utf-8"))
    for scenario in doc["scenarios"]:
        scenario["settings"]["house_profile_id"] = ""
    scenarios.write_text(json.dumps(doc), encoding="utf-8")
    house.write_text(json.dumps({"earnie_data_model": 5, "profiles": []}), encoding="utf-8")
    yield
    for path, data in originals.items():
        path.write_bytes(data)


def test_new_profile_needs_grid_area_before_import(
    no_house_profile, loxone_credentials, loxapp3
) -> None:
    at = _run()

    assert at.selectbox(key=_GRID_AREA).value is None
    assert at.button(key=_BUTTON).disabled
    assert any("Netzbereich wählen" in w for w in messages(at)["warning"])

    at.selectbox(key=_GRID_AREA).set_value("AT-VBG").run(timeout=_TIMEOUT_S)
    assert not at.button(key=_BUTTON).disabled
    at = _click(at)

    assert_clean(at)
    house, _config = _paths()
    profiles = json.loads(house.read_text(encoding="utf-8"))["profiles"]
    assert [p["id"] for p in profiles] == ["live"]
    assert profiles[0]["netznutzung"]["area_id"] == "AT-VBG"


def test_grid_area_select_hidden_when_a_profile_exists(loxone_credentials, loxapp3) -> None:
    at = _run()

    assert not [sb for sb in at.selectbox if sb.key == _GRID_AREA]
    assert not at.button(key=_BUTTON).disabled
