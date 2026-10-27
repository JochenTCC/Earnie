"""AppTest-Smoketests für die Seite Tarife (eingebetteter Edibert-Editor, Edibert P7)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_tariffs.py"
_SCENARIO_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"
_PREFIX = "earnie.tariffs."


def _config_dir() -> Path:
    return Path(os.environ["EARNIE_TARIFFS_PATH"]).parent


def _start() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT), default_timeout=60).run()
    assert not at.exception
    return at


def _form_key(at: AppTest, name: str) -> str:
    return f"{_PREFIX}{at.session_state[_PREFIX + 'ui.ver']}.{name}"


def test_renders_with_profile_select_and_read_only_house():
    at = _start()
    assert at.title[0].value == "💶 Tarife"
    assert any(sb.label == "Hausprofil" for sb in at.selectbox)
    captions = " ".join(c.value for c in at.caption)
    assert "Hausprofil „" in captions
    assert "Diese Werte kommen aus dem Hausprofil" in captions
    assert not (_config_dir() / "house.json").exists()


def test_editor_keys_stay_behind_the_prefix():
    at = _start()
    at.button(key=_PREFIX + "new.import").click().run()
    widgets = [
        *at.button, *at.selectbox, *at.text_input, *at.text_area, *at.number_input,
        *at.checkbox, *at.radio, *at.multiselect,
    ]
    keys = {w.key for w in widgets if w.key}
    leaked = sorted(k for k in keys if not k.startswith((_PREFIX, "tariffs_page_")))
    assert leaked == []
    assert any(k.startswith(_PREFIX) for k in keys)


def test_created_user_tariff_is_saved_and_selectable_in_scenarios():
    at = _start()
    at.button(key=_PREFIX + "new.import").click().run()
    at.text_input(key=_form_key(at, "label")).set_value("Mein Fixtarif").run()
    at.number_input(key=_form_key(at, "price")).set_value(24.5).run()
    assert not at.exception
    at.button(key=_PREFIX + "ui.save").click().run()
    assert not at.exception
    saved = json.loads((_config_dir() / "user_tariffs.json").read_text(encoding="utf-8"))
    assert saved["tariff_format"] == 1
    (tariff,) = saved["import_tariffs"]
    assert (tariff["id"], tariff["fix_cent_kwh"]) == ("user_mein_fixtarif", 24.5)
    assert any("user_mein_fixtarif" in s.value for s in at.success)

    scenarios = AppTest.from_file(str(_SCENARIO_SCRIPT), default_timeout=60).run()
    assert not scenarios.exception
    options = next(sb for sb in scenarios.selectbox if sb.label == "Bezugstarif").options
    assert "Mein Fixtarif · Benutzertarif" in options


def test_request_opens_the_user_tariff():
    from ui.pages.page_tariffs import REQUEST_KEY

    (_config_dir() / "user_tariffs.json").write_text(
        json.dumps(
            {
                "tariff_format": 1,
                "import_tariffs": [
                    {
                        "id": "user_offen", "label": "Offener Tarif", "type": "fixed_cent",
                        "land": "AT", "supplier_id": "user_me", "fix_cent_kwh": 21.0,
                        "vat_percent": 20,
                    }
                ],
                "export_tariffs": [],
            }
        ),
        encoding="utf-8",
    )
    at = AppTest.from_file(str(_SCRIPT), default_timeout=60)
    at.session_state[REQUEST_KEY] = {"profile_id": None, "open": ("import", "user_offen")}
    at.run()
    assert not at.exception
    assert at.text_input(key=_form_key(at, "label")).value == "Offener Tarif"


def test_request_for_an_unknown_tariff_shows_an_error():
    from ui.pages.page_tariffs import REQUEST_KEY

    at = AppTest.from_file(str(_SCRIPT), default_timeout=60)
    at.session_state[REQUEST_KEY] = {"profile_id": None, "open": ("import", "user_fehlt")}
    at.run()
    assert not at.exception
    assert any("user_fehlt" in e.value for e in at.error)


def _write_user_tariff(tariff_id: str = "user_offen") -> None:
    (_config_dir() / "user_tariffs.json").write_text(
        json.dumps(
            {
                "tariff_format": 1,
                "import_tariffs": [
                    {
                        "id": tariff_id, "label": "Offener Tarif", "type": "fixed_cent",
                        "land": "AT", "supplier_id": "user_me", "fix_cent_kwh": 21.0,
                        "vat_percent": 20,
                    }
                ],
                "export_tariffs": [],
            }
        ),
        encoding="utf-8",
    )


def _use_in_scenario(scenario_id: str, tariff_id: str) -> None:
    path = Path(os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"])
    doc = json.loads(path.read_text(encoding="utf-8"))
    for entry in doc["scenarios"]:
        if entry["id"] == scenario_id:
            entry["settings"]["import_tariff_id"] = tariff_id
    path.write_text(json.dumps(doc), encoding="utf-8")


def _open(tariff_id: str = "user_offen") -> AppTest:
    from ui.pages.page_tariffs import REQUEST_KEY

    at = AppTest.from_file(str(_SCRIPT), default_timeout=60)
    at.session_state[REQUEST_KEY] = {"profile_id": None, "open": ("import", tariff_id)}
    at.run()
    assert not at.exception
    return at


def _user_ids() -> list[str]:
    doc = json.loads((_config_dir() / "user_tariffs.json").read_text(encoding="utf-8"))
    return [t["id"] for t in doc["import_tariffs"]]


def test_unused_user_tariff_is_deleted_without_asking():
    _write_user_tariff()
    at = _open()
    at.button(key=_PREFIX + "delete").click().run()
    assert not at.exception
    assert _user_ids() == []
    assert not at.error, [e.value for e in at.error]


def test_delete_of_a_used_user_tariff_names_the_scenarios_and_waits():
    _write_user_tariff()
    _use_in_scenario("entity_test", "user_offen")
    at = _open()
    at.button(key=_PREFIX + "delete").click().run()
    assert not at.exception
    assert _user_ids() == ["user_offen"]
    (warning,) = [w.value for w in at.warning if "user_offen" in w.value]
    assert "Bezugstarif in Szenario entity_test" in warning
    at.button(key=_PREFIX + "delete.cancel").click().run()
    assert _user_ids() == ["user_offen"]


def test_confirmed_delete_reports_the_scenario_in_the_plausibility_check():
    _write_user_tariff()
    _use_in_scenario("entity_test", "user_offen")
    at = _open()
    at.button(key=_PREFIX + "delete").click().run()
    at.button(key=_PREFIX + "delete.confirm").click().run()
    assert not at.exception
    assert _user_ids() == []
    errors = " ".join(e.value for e in at.error)
    assert "Szenario 'entity_test': unbekannte import_tariff_id 'user_offen'" in errors
    at.run()  # the check runs once per write, not on every rerun
    assert not at.error


def test_save_runs_the_plausibility_check_once_without_findings():
    from ui.pages import page_tariffs

    at = _start()
    at.button(key=_PREFIX + "new.import").click().run()
    at.text_input(key=_form_key(at, "label")).set_value("Mein Fixtarif").run()
    at.number_input(key=_form_key(at, "price")).set_value(24.5).run()
    at.button(key=_PREFIX + "ui.save").click().run()
    assert not at.exception
    assert page_tariffs._CHECK_KEY not in at.session_state
    assert not at.error, [e.value for e in at.error]
