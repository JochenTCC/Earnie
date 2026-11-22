"""Setup pages: config-migration questions/exports, Smarthome-Backend LAN subnet / import
section / Docker-bridge HA shortcut, own fixed feed-in price, config-pack session reset.

Covers helpers no other test executed (full-suite coverage run 2026-11-22). Network scans
are always mocked; files land in the isolated config copy of ``tests/apptest/conftest.py``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from runtime_store.migration.types import ManualTodo, MigrationPlan, MigrationReport, Question

_SCRIPTS = Path(__file__).parent / "scripts"
_TIMEOUT = 30


# --- Konfigurations-Migration -------------------------------------------------------------


def _plan(**overrides) -> MigrationPlan:
    base = dict(
        config_dir="/tmp/earnie-mig-test",
        from_model=3,
        to_model=4,
        pending_step_ids=("dm4.topology",),
        questions=(),
        blockers=(),
        manual_todos=(),
        file_diffs=(),
        can_run=True,
    )
    base.update(overrides)
    return MigrationPlan(**base)


def _migration_page(monkeypatch, plan: MigrationPlan) -> AppTest:
    monkeypatch.setattr("ui.pages.page_config_migration.plan_for_active_config", lambda: plan)
    at = AppTest.from_file(str(_SCRIPTS / "run_page_config_migration.py"), default_timeout=_TIMEOUT).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


_VAT = Question(
    id="dm5.vat.rate",
    step_id="dm5.vat",
    prompt_de="Umsatzsteuersatz (%)",
    kind="number",
    required=True,
    default=20.0,
)


def _run_mock(monkeypatch) -> MagicMock:
    run = MagicMock(
        return_value=MigrationReport(
            backup_dir="/tmp/backups/x", applied_step_ids=("dm5.vat",), manual_todos=(), written_files=()
        )
    )
    monkeypatch.setattr("ui.pages.page_config_migration.run_migration", run)
    monkeypatch.setattr("ui.pages.page_config_migration.continue_after_migration", MagicMock())
    return run


def _answers(run: MagicMock) -> dict:
    call = run.call_args
    return call.args[1] if len(call.args) > 1 else call.kwargs["answers"]


def test_number_question_starts_empty_and_takes_suggestion_on_click(monkeypatch):
    run = _run_mock(monkeypatch)
    at = _migration_page(monkeypatch, _plan(questions=(_VAT,)))
    number = next(n for n in at.number_input if n.label == "Umsatzsteuersatz (%)")
    assert number.value is None
    assert number.proto.placeholder == "Vorschlag: 20"
    take = next(b for b in at.button if b.label == "Vorschlag übernehmen (20)")
    take.click().run()
    assert not at.exception
    number = next(n for n in at.number_input if n.label == "Umsatzsteuersatz (%)")
    assert number.value == 20.0
    # Answered: the suggestion button is gone, the answer goes to the runner.
    assert not [b for b in at.button if b.label.startswith("Vorschlag übernehmen")]
    next(b for b in at.button if b.label == "Backup anlegen und migrieren").click().run()
    assert _answers(run)["dm5.vat.rate"] == 20.0


def test_optional_number_question_without_suggestion(monkeypatch):
    question = Question(id="dm5.x", step_id="dm5.x", prompt_de="Faktor", kind="number", required=False)
    run = _run_mock(monkeypatch)
    at = _migration_page(monkeypatch, _plan(questions=(question,)))
    number = next(n for n in at.number_input if n.label == "Faktor (optional)")
    assert number.proto.placeholder == "Bitte eingeben"
    assert not [b for b in at.button if b.label.startswith("Vorschlag übernehmen")]
    number.set_value(7.7).run()
    next(b for b in at.button if b.label == "Backup anlegen und migrieren").click().run()
    assert _answers(run)["dm5.x"] == 7.7


def test_manual_todo_with_unknown_export_kind_fails_loud(monkeypatch):
    todo = ManualTodo(step_id="dm4.topology", text_de="Liste exportieren.", export_kind="signal_csv")
    at = _migration_page(monkeypatch, _plan(manual_todos=(todo,)))
    assert "Unbekannter export_kind: 'signal_csv'" in [e.value for e in at.error]
    assert not at.get("download_button")


def test_manual_todo_export_offers_download(monkeypatch):
    monkeypatch.setattr(
        "ui.pages.page_config_migration.resolve_export_bytes", lambda kind: (b"a;b\n", f"{kind}.csv")
    )
    todo = ManualTodo(step_id="dm4.topology", text_de="Liste exportieren.", export_kind="signal_csv")
    at = _migration_page(monkeypatch, _plan(manual_todos=(todo,)))
    assert not at.error
    [download] = at.get("download_button")
    assert download.proto.label == "Download (signal_csv)"
    assert "cfg_mig_export_0_signal_csv" in download.proto.id


# --- Smarthome-Backend ----------------------------------------------------------------------


@pytest.fixture
def _no_scan(monkeypatch):
    for name in ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS", "EARNIE_INSTALL_CONTEXT"):
        monkeypatch.delenv(name, raising=False)
    mock = MagicMock(return_value=[])
    monkeypatch.setattr("ui.pages.page_smarthome_backend.scan_for_backends", mock)
    return mock


def test_lan_subnet_save_writes_dotenv_and_environment(monkeypatch, _no_scan):
    monkeypatch.setenv("EARNIE_LAN_SUBNET", "")  # restored after the test
    monkeypatch.setattr("ui.pages.page_smarthome_backend.resolve_scan_hosts", lambda: None)
    at = AppTest.from_file(str(_SCRIPTS / "run_form_lan_subnet.py"), default_timeout=_TIMEOUT).run()
    at.text_input(key="sb_lan_subnet_input").set_value(" 192.168.178.0/24 ")
    at.button(key="sb_lan_subnet_save").click().run()
    assert not at.exception, [e.value for e in at.exception]
    dotenv = Path(os.environ["EARNIE_DOTENV_PATH"]).read_text(encoding="utf-8")
    assert "EARNIE_LAN_SUBNET=192.168.178.0/24" in dotenv.splitlines()
    assert os.environ["EARNIE_LAN_SUBNET"] == "192.168.178.0/24"


def test_lan_subnet_invalid_value_writes_nothing(monkeypatch, _no_scan):
    monkeypatch.setenv("EARNIE_LAN_SUBNET", "")
    monkeypatch.setattr("ui.pages.page_smarthome_backend.resolve_scan_hosts", lambda: None)
    dotenv = Path(os.environ["EARNIE_DOTENV_PATH"])
    before = dotenv.read_bytes() if dotenv.exists() else None
    at = AppTest.from_file(str(_SCRIPTS / "run_form_lan_subnet.py"), default_timeout=_TIMEOUT).run()
    at.text_input(key="sb_lan_subnet_input").set_value("192.168.178.1")
    at.button(key="sb_lan_subnet_save").click().run()
    assert any(e.value.startswith("Ungültig") for e in at.error)
    assert (dotenv.read_bytes() if dotenv.exists() else None) == before
    assert os.environ["EARNIE_LAN_SUBNET"] == ""


def _import_section_app(backend: str):
    from ui.pages.page_smarthome_backend import _render_backend_import_section

    _render_backend_import_section(backend)


def test_backend_import_section_ha_says_not_available():
    from runtime_store.ehal_setup import BACKEND_HA

    at = AppTest.from_function(_import_section_app, default_timeout=_TIMEOUT, kwargs={"backend": BACKEND_HA}).run()
    assert not at.exception
    assert [c.value for c in at.caption] == [
        "Automatischer Verbraucher-/EHAL-Import ist für Home Assistant noch nicht verfügbar."
    ]


def test_backend_import_section_loxone_renders_greenfield_import(monkeypatch):
    from runtime_store.ehal_setup import BACKEND_LOXONE

    greenfield = MagicMock()
    monkeypatch.setattr("ui.ehal_greenfield_import.render_greenfield_import_section", greenfield)
    at = AppTest.from_function(
        _import_section_app, default_timeout=_TIMEOUT, kwargs={"backend": BACKEND_LOXONE}
    ).run()
    assert not at.exception
    greenfield.assert_called_once_with()
    assert not at.caption


def _bridge(monkeypatch, *, bridge: bool) -> AppTest:
    page = "ui.pages.page_smarthome_backend"
    monkeypatch.setattr(f"{page}.is_homeassistant_addon_context", lambda: False)
    monkeypatch.setattr(f"{page}.is_bridge_network_without_lan_subnet", lambda: bridge)
    monkeypatch.setattr(f"{page}.resolve_scan_hosts", lambda: ["192.168.178.0/24"])
    at = AppTest.from_file(str(_SCRIPTS / "run_page_smarthome_backend.py"), default_timeout=_TIMEOUT).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_docker_bridge_offers_home_assistant_and_saves_backend(monkeypatch, _no_scan):
    at = _bridge(monkeypatch, bridge=True)
    assert any(i.value.startswith("Im Docker-Bridge-Netz erreicht mDNS oft kein Home Assistant.") for i in at.info)
    at.button(key="sb_ha_bridge_form_submit").click().run()
    assert not at.exception, [e.value for e in at.exception]
    config = json.loads(Path(os.environ["EARNIE_CONFIG_PATH"]).read_text(encoding="utf-8"))
    assert config["ehal"]["backend"] == "ha"


def test_no_bridge_shortcut_outside_docker_bridge(monkeypatch, _no_scan):
    at = _bridge(monkeypatch, bridge=False)
    assert not any(i.value.startswith("Im Docker-Bridge-Netz") for i in at.info)
    assert "sb_ha_bridge_form_adapter_id" not in [t.key for t in at.text_input]


# --- Szenarienkonfigurator: own fixed feed-in price ---------------------------------------


def _stored_settings(scenario_id: str) -> dict:
    doc = json.loads(Path(os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"]).read_text(encoding="utf-8"))
    return next(s for s in doc["scenarios"] if s["id"] == scenario_id)["settings"]


def _scenario_session() -> AppTest:
    from tests.apptest.fields import SCENARIO_RADIO_LABEL
    from tests.apptest.helpers import open_scenario

    at = AppTest.from_file(str(_SCRIPTS / "run_page_scenario_editor.py"), default_timeout=60).run()
    open_scenario(at, SCENARIO_RADIO_LABEL)
    assert not at.exception
    return at


def test_own_fixed_feed_in_price_starts_empty_saves_and_reloads():
    from tests.apptest.fields import SCENARIO_ID

    prefix = f"{SCENARIO_ID}__"
    at = _scenario_session()
    export = at.selectbox(key=prefix + "scenario_export")
    assert not [n for n in at.number_input if n.key == prefix + "scenario_user_export_cent"]
    export.set_value(next(o for o in export.options if o.startswith("Eigener Festpreis"))).run()
    assert not at.exception
    cent = at.number_input(key=prefix + "scenario_user_export_cent")
    assert cent.value is None
    assert cent.label == "Einspeisevergütung (Cent/kWh)"
    assert _stored_settings(SCENARIO_ID).get("export_tariff_id") != "__user_fixed__"

    cent.set_value(8.25).run()
    settings = _stored_settings(SCENARIO_ID)
    assert (settings["export_tariff_id"], settings["user_export_cent_kwh"]) == ("__user_fixed__", 8.25)
    assert _scenario_session().number_input(key=prefix + "scenario_user_export_cent").value == 8.25


# --- Config pack import: session reset ----------------------------------------------------


def _clear_session_app():
    import streamlit as st

    from ui.config_pack import _clear_session_after_config_import

    if "cov_done" not in st.session_state:
        for key in (
            "house_profile_select",
            "scenario_editor_x",
            "planning_pv_select",
            "planning_battery_select",
            "_auto_persist_fp::planning_pv::a",
            "live_display_bundle",
            "keep_me",
            "planning_inv_select",
        ):
            st.session_state[key] = 1
        _clear_session_after_config_import()
        st.session_state["cov_done"] = True
    st.session_state["cov_keys"] = sorted(k for k in st.session_state if k not in ("cov_done", "cov_keys"))


def test_clear_session_after_config_import_drops_editor_state(monkeypatch):
    from ui import chart_consumer_stack

    monkeypatch.setitem(chart_consumer_stack._STACK_ORDER_BY_SA0, "stale", ["x"])
    at = AppTest.from_function(_clear_session_app, default_timeout=_TIMEOUT).run()
    assert not at.exception, [e.value for e in at.exception]
    # Prefixes house_profile_/scenario_editor_/planning_pv_/planning_battery_/_auto_persist_fp::
    # and the live display bundle go; other keys stay.
    assert at.session_state["cov_keys"] == ["keep_me", "planning_inv_select"]
    assert "stale" not in chart_consumer_stack._STACK_ORDER_BY_SA0
