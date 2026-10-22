"""Ebene 1 (T1, T3, T5, Logik): EHAL-Signalliste in EHAL-Com (``ui/ehal_signal_list.py``).

Die Optionsschalter (``ehal_sig_opt::<binding_key>``) legen den Binding-Schlüssel mit leerem
Wert in ``house_profiles.json`` bzw. ``components.json`` an (Ein) oder entfernen ihn (Aus).
Pflichtsignale haben keinen Schalter. Der Export (Host, Port, Umfang) wird nicht gespeichert.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from house_config.components_store import clear_components_doc_cache
from tests.apptest.helpers import assert_clean, file_snapshot, messages

_SCRIPT = Path(__file__).parent / "scripts" / "run_form_signal_list.py"
_TIMEOUT_S = 30.0
_PREFIX = "ehal_sig_opt::"

# Binding-Schlüssel, Datei ("house" | "comp"), Pfad zum ehal_bindings-Objekt in der Rohdatei.
SIGNALS = [
    ("ess.test_battery.get_ess_soc_max", "comp", ("batteries", 0, "ehal_bindings")),
    ("pv.test_pv.sens_pv_production_active", "comp", ("pv_systems", 0, "ehal_bindings")),
    ("inv.wr_main.get_inv_max_ac_power", "comp", ("inverters", 0, "ehal_bindings")),
    ("get_grid_export_power_limit", "house", ("plant", "ehal_bindings")),
    ("sens_power_consumers", "house", ("plant", "ehal_bindings")),
    ("heatpump.wp.sens_power_act", "house", ("profiles", 0, "consumers", 0, "ehal_bindings")),
]
_IDS = [signal[0] for signal in SIGNALS]
_REQUIRED_EHAL_ID = "ess.test_battery.sens_ess_soc"


def _run() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert_clean(at)
    return at


def _path(kind: str) -> Path:
    env = "EARNIE_HOUSE_PROFILES_PATH" if kind == "house" else "EARNIE_COMPONENTS_PATH"
    return Path(os.environ[env])


def _bindings(kind: str, steps: tuple) -> dict:
    node = json.loads(_path(kind).read_text(encoding="utf-8"))
    for step in steps[:-1]:
        node = node[step]
    # Das letzte Binding-Objekt wird mit dem letzten Schlüssel ganz entfernt.
    return node.get(steps[-1], {})


def _toggle(at: AppTest, key: str, value: bool) -> AppTest:
    at.checkbox(key=_PREFIX + key).set_value(value)
    return at.run(timeout=_TIMEOUT_S)


def _row(at: AppTest, key: str) -> dict:
    """Tabellenzeile zum Binding-Schlüssel (Anlagensignale heißen in der Tabelle ``grid.meter.<key>``)."""
    frame = at.dataframe[0].value
    return frame[frame["EHAL-ID"].isin([key, f"grid.meter.{key}"])].iloc[0].to_dict()


# --- T1: Ein/Aus überlebt Speichern und neue Session -------------------------------------


@pytest.mark.parametrize("key,kind,steps", SIGNALS, ids=_IDS)
def test_t1_activation_is_persisted_and_shown_in_new_session(key, kind, steps) -> None:
    at = _toggle(_run(), key, True)

    assert_clean(at)
    assert not at.error
    assert _bindings(kind, steps)[key] == ""
    fresh = _run()
    assert fresh.checkbox(key=_PREFIX + key).value is True
    assert _row(fresh, key)["aktiviert"] == "ja"


@pytest.mark.parametrize("key,kind,steps", SIGNALS, ids=_IDS)
def test_t1_deactivation_removes_the_key(key, kind, steps) -> None:
    at = _toggle(_run(), key, True)

    at = _toggle(at, key, False)

    assert_clean(at)
    assert key not in _bindings(kind, steps)
    fresh = _run()
    assert fresh.checkbox(key=_PREFIX + key).value is False
    assert _row(fresh, key)["aktiviert"] == "nein"


def test_t5_several_toggles_in_one_run_are_all_persisted() -> None:
    at = _run()
    picks = [SIGNALS[0], SIGNALS[3], SIGNALS[5]]
    for key, _kind, _steps in picks:
        at.checkbox(key=_PREFIX + key).set_value(True)
    at.run(timeout=_TIMEOUT_S)

    assert_clean(at)
    for key, kind, steps in picks:
        assert key in _bindings(kind, steps), key


def test_other_bindings_stay_when_one_signal_is_toggled() -> None:
    at = _toggle(_run(), SIGNALS[3][0], True)
    at = _toggle(at, SIGNALS[4][0], True)

    _toggle(at, SIGNALS[3][0], False)

    plant = _bindings("house", ("plant", "ehal_bindings"))
    assert SIGNALS[3][0] not in plant and plant[SIGNALS[4][0]] == ""


# --- Logik: Tabelle und Pflichtsignale ---------------------------------------------------


def test_required_signals_have_no_switch_and_are_marked_required() -> None:
    at = _run()

    assert _PREFIX + _REQUIRED_EHAL_ID not in {c.key for c in at.checkbox}
    row = _row(at, _REQUIRED_EHAL_ID)
    assert row["Pflicht"] == "Pflicht" and row["aktiviert"] == "ja"
    assert row["Richtung"] == "Lesen"


def test_every_optional_row_has_a_switch_and_starts_off() -> None:
    at = _run()

    frame = at.dataframe[0].value
    optional = {i.removeprefix("grid.meter.") for i in frame[frame["Pflicht"] == "optional"]["EHAL-ID"]}
    switches = {c.key.removeprefix(_PREFIX): c.value for c in at.checkbox if c.key.startswith(_PREFIX)}
    # ``request_optimize`` ist optional, hat aber keinen Binding-Schlüssel und keinen Schalter.
    assert set(switches) == optional - {"request_optimize"}
    assert not any(switches.values())


def test_activation_changes_the_match_text_of_the_row() -> None:
    key = "ess.test_battery.get_ess_soc_max"
    before = _row(_run(), key)

    after = _row(_toggle(_run(), key, True), key)

    assert "nicht aktiviert" in before["Match"]
    assert after["Match"] != before["Match"] and "nicht aktiviert" not in after["Match"]


# --- Export ------------------------------------------------------------------------------


@pytest.fixture
def export_spy(monkeypatch):
    calls: list[dict] = []

    def fake_build_export_zip(house, components, *, host, port, mode):
        calls.append({"host": host, "port": port, "mode": mode})
        return b"PK-fake"

    monkeypatch.setattr("ui.ehal_signal_list.build_export_zip", fake_build_export_zip)
    monkeypatch.setattr("ui.ehal_signal_list._default_host", lambda: "192.168.1.10")
    return calls


def _download_buttons(at: AppTest) -> list:
    return at.get("download_button")


def test_export_offers_download_with_default_host_port_and_mode(export_spy) -> None:
    at = _run()

    assert at.text_input(key="ehal_signal_export_host").value == "192.168.1.10"
    assert at.radio(key="ehal_signal_export_mode").value == "needed"
    assert len(_download_buttons(at)) == 1
    assert export_spy[-1] == {"host": "192.168.1.10", "port": 8541, "mode": "needed"}


def test_export_passes_changed_values_through(export_spy) -> None:
    at = _run()

    at.text_input(key="ehal_signal_export_host").set_value("  10.0.0.5 ")
    at.number_input(key="ehal_signal_export_port").set_value(9000)
    at.radio(key="ehal_signal_export_mode").set_value("all")
    at.run(timeout=_TIMEOUT_S)

    assert_clean(at)
    assert export_spy[-1] == {"host": "10.0.0.5", "port": 9000, "mode": "all"}


def test_export_without_host_hides_download_and_shows_hint(export_spy) -> None:
    at = _run()

    at.text_input(key="ehal_signal_export_host").set_value("   ").run(timeout=_TIMEOUT_S)

    assert not _download_buttons(at)
    assert "Host eingeben, um den ZIP-Download freizuschalten." in messages(at)["caption"]


def test_export_error_is_shown_as_message_not_as_exception(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise ValueError("boom")

    monkeypatch.setattr("ui.ehal_signal_list.build_export_zip", boom)
    monkeypatch.setattr("ui.ehal_signal_list._default_host", lambda: "192.168.1.10")

    at = _run()

    assert messages(at)["error"] == ["Export fehlgeschlagen: boom"]
    assert not _download_buttons(at)


def test_export_settings_are_not_persisted(export_spy) -> None:
    at = _run()
    at.text_input(key="ehal_signal_export_host").set_value("10.0.0.5").run(timeout=_TIMEOUT_S)

    fresh = _run()

    assert fresh.text_input(key="ehal_signal_export_host").value == "192.168.1.10"


def test_page_render_does_not_write_config_files() -> None:
    hp, cp = _path("house"), _path("comp")
    first = _run()
    before = (file_snapshot(hp), file_snapshot(cp))

    _run()

    assert (file_snapshot(hp), file_snapshot(cp)) == before
    assert first.dataframe


# --- Bekannte Fehler ---------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="ehal_signal_list._persist_docs: ConfigReadOnlyError im Shadow-Modus wird nicht "
    "abgefangen (Traceback statt Hinweis; Backlog-Bugfixes)",
)
def test_t3_shadow_mode_toggle_shows_hint_and_keeps_files(monkeypatch) -> None:
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    hp, cp = _path("house"), _path("comp")
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    before = (file_snapshot(hp), file_snapshot(cp))

    at = _toggle(at, "get_grid_export_power_limit", True)

    assert_clean(at)
    assert (file_snapshot(hp), file_snapshot(cp)) == before
    assert any("Shadow" in text for text in messages(at)["caption"] + messages(at)["warning"])


def _break_components() -> Path:
    path = _path("comp")
    path.write_text("{ das ist kein json", encoding="utf-8")
    clear_components_doc_cache()
    return path


@pytest.mark.xfail(
    strict=True,
    reason="ehal_signal_list._load_docs: `except Exception` ersetzt eine unlesbare components.json "
    "still durch ein leeres Dokument, die Tabelle zeigt keinen Fehler (Backlog-Bugfixes)",
)
def test_t3_unreadable_components_file_is_reported() -> None:
    _break_components()

    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)

    assert messages(at)["error"] or messages(at)["warning"]


@pytest.mark.xfail(
    strict=True,
    reason="ehal_signal_list._load_docs/_persist_docs: nach dem stillen Ersatz wird die unlesbare "
    "components.json beim Umschalten eines Signals mit einem leeren Dokument überschrieben "
    "(Datenverlust; Backlog-Bugfixes)",
)
def test_t3_toggle_never_overwrites_an_unreadable_components_file() -> None:
    path = _break_components()
    before = path.read_bytes()
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)

    at = _toggle(at, "get_grid_export_power_limit", True)

    assert path.read_bytes() == before
    assert not at.exception
