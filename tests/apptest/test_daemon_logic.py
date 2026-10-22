"""Logik- und Zustandstests Optimierer-Dienst (D1-D8), ``ui/pages/page_daemon.py``.

Die Lebenszyklus-Funktionen sind durch die Fixture ``fake_daemon`` ersetzt, es startet
nie ein echter ``main.py``-Prozess. Zustände und Texte stehen in ``states.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import config
from tests.apptest.helpers import assert_clean, click, file_snapshot, messages
from tests.apptest.states import (
    DAEMON_ACTIONS,
    DAEMON_STATES,
    DAEMON_SUCCESS_TEXT,
    MIXED_LOG,
)

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_daemon.py"
_TIMEOUT_S = 30.0


def _run() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert_clean(at)
    return at


def _markdown(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def _log_blocks(at: AppTest) -> list:
    # Die Seite zeigt weitere Code-Blöcke (z. B. die Nutzungsstatistik als json).
    return [c for c in at.code if c.language == "log"]


def _log_text(at: AppTest) -> str:
    return "\n".join(c.value for c in _log_blocks(at))


# --- D1: Zustand -> erlaubte Aktionen und Anzeige ---------------------------------------


@pytest.mark.parametrize("state,label,pid,start_ok,stop_ok,restart_ok", DAEMON_STATES)
def test_d1_buttons_and_status_follow_state(
    fake_daemon, state, label, pid, start_ok, stop_ok, restart_ok
) -> None:
    fake_daemon.state = state

    at = _run()

    text = _markdown(at)
    assert f"**Status:** {label}" in text
    assert f"**PID:** {pid}" in text
    assert f"`{fake_daemon.lock_path}`" in text
    assert at.button(key="daemon_start").disabled is not start_ok
    assert at.button(key="daemon_stop").disabled is not stop_ok
    assert at.button(key="daemon_restart").disabled is not restart_ok
    assert fake_daemon.calls == []


# --- D2: Aktion -> Funktion genau einmal, Folgezustand ----------------------------------


@pytest.mark.parametrize("key,before,function,after,label_after", DAEMON_ACTIONS)
def test_d2_action_calls_function_once_and_shows_new_state(
    fake_daemon, key, before, function, after, label_after
) -> None:
    fake_daemon.state = before
    at = _run()

    at = click(at, key)

    assert_clean(at)
    assert fake_daemon.calls == [function]
    assert fake_daemon.state == after
    assert f"**Status:** {label_after}" in _markdown(at)
    assert not at.error


@pytest.mark.xfail(
    strict=True,
    reason="page_daemon._run_lifecycle_actions: st.success vor st.rerun() wird verworfen "
    "(Backlog-Bugfixes, Erfolgsmeldungen)",
)
@pytest.mark.parametrize("key,before,function,after,label_after", DAEMON_ACTIONS)
def test_d2_action_confirmation_is_visible(
    fake_daemon, key, before, function, after, label_after
) -> None:
    fake_daemon.state = before
    at = click(_run(), key)

    assert DAEMON_SUCCESS_TEXT[function] in messages(at)["success"]


# --- D3: DaemonError wird zur Meldung ---------------------------------------------------


@pytest.mark.parametrize("key,before,function,after,label_after", DAEMON_ACTIONS)
def test_d3_daemon_error_is_shown_as_error_not_as_exception(
    fake_daemon, key, before, function, after, label_after
) -> None:
    fake_daemon.state = before
    fake_daemon.fail_with = "Lock main.lock belegt (PID 1234)"
    at = _run()

    at = click(at, key)

    assert_clean(at)
    assert messages(at)["error"] == ["Lock main.lock belegt (PID 1234)"]
    assert fake_daemon.calls == [function]
    assert fake_daemon.state == before  # fehlgeschlagene Aktion ändert den Zustand nicht


# --- D4: Silent-Schalter (Datei, Laufzeitzustand) ---------------------------------------


@pytest.mark.parametrize("target", [True, False])
def test_d4_silent_toggle_writes_file_and_switches_runtime_state(
    fake_daemon, local_settings: Path, target: bool
) -> None:
    at = _run()
    toggle = at.toggle(key="daemon_silent_mode")
    if toggle.value is target:  # erst auf das Gegenteil, damit der Zielwert eine Änderung ist
        toggle.set_value(not target).run(timeout=_TIMEOUT_S)
        toggle = at.toggle(key="daemon_silent_mode")

    toggle.set_value(target).run(timeout=_TIMEOUT_S)

    assert_clean(at)
    assert json.loads(local_settings.read_text(encoding="utf-8"))["silent_mode"] is target
    assert config.is_silent_mode() is target
    assert at.toggle(key="daemon_silent_mode").value is target


# --- D5: Shadow-Modus -------------------------------------------------------------------


def test_d5_shadow_mode_locks_toggle_shows_hint_and_writes_nothing(
    fake_daemon, shadow_mode: Path
) -> None:
    at = _run()

    toggle = at.toggle(key="daemon_silent_mode")
    assert toggle.disabled
    assert toggle.value is True  # Shadow ist immer silent
    assert any("Shadow-Modus" in c for c in messages(at)["caption"])
    assert config.is_silent_mode() is True
    assert not shadow_mode.exists()


# --- D6: Log-Level-Filter ---------------------------------------------------------------


def test_d6_default_filter_hides_debug_and_reports_counts(fake_daemon, log_file) -> None:
    log_file(MIXED_LOG)

    at = _run()

    shown = _log_text(at)
    assert "debug eins" not in shown
    assert "info eins" in shown and "kritisch eins" in shown
    assert "Anzeige: 7 von 8 Zeilen (Level-Filter)." in messages(at)["caption"]


def test_d6_deselecting_levels_keeps_lines_without_level(fake_daemon, log_file) -> None:
    log_file(MIXED_LOG)
    at = _run()

    at.multiselect(key="daemon_log_levels").set_value(["ERROR", "CRITICAL"]).run(timeout=_TIMEOUT_S)

    assert_clean(at)
    shown = _log_text(at)
    assert "fehler eins" in shown and "kritisch eins" in shown
    assert "info eins" not in shown and "warnung eins" not in shown
    # Die Traceback-Zeilen tragen kein [LEVEL] und bleiben sichtbar.
    assert "Traceback (most recent call last):" in shown
    assert '  File "x.py", line 1, in <module>' in shown
    assert "Anzeige: 4 von 8 Zeilen (Level-Filter)." in messages(at)["caption"]


def test_d6_all_levels_selected_shows_no_filter_hint(fake_daemon, log_file) -> None:
    log_file(MIXED_LOG)
    at = _run()

    at.multiselect(key="daemon_log_levels").set_value(
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    ).run(timeout=_TIMEOUT_S)

    assert not any(c.startswith("Anzeige:") for c in messages(at)["caption"])
    assert "debug eins" in _log_text(at)


# --- D7: Logdatei fehlt / leer / sehr groß ----------------------------------------------


def test_d7_missing_log_file_shows_info(fake_daemon, log_file) -> None:
    assert not log_file.path.exists()

    at = _run()

    assert any("Logdatei nicht gefunden" in text for text in messages(at)["info"])
    assert not _log_blocks(at)


def test_d7_empty_log_file_shows_caption(fake_daemon, log_file) -> None:
    log_file("")

    at = _run()

    assert "Logdatei ist leer." in messages(at)["caption"]
    assert not _log_blocks(at)


def test_d7_large_log_file_shows_only_last_lines_without_partial_first_line(
    fake_daemon, log_file
) -> None:
    # 400 Zeilen à ca. 2 KB: die letzten 256 KB enthalten weniger als 200 Zeilen und beginnen
    # mitten in einer Zeile. Die halbe erste Zeile darf nicht angezeigt werden.
    padding = "x" * 2000
    lines = [f"2026-10-22 10:00:00 [INFO] zeile {number:04d} {padding}" for number in range(400)]
    log_file("\n".join(lines) + "\n")

    at = _run()

    shown_lines = _log_text(at).splitlines()
    assert 0 < len(shown_lines) < 200
    assert all(line.startswith("2026-10-22 10:00:00 [INFO] zeile ") for line in shown_lines)
    assert all(line.endswith(padding) for line in shown_lines)
    assert shown_lines[-1].split()[4] == "0399"


def test_d7_log_tail_is_limited_to_200_lines(fake_daemon, log_file) -> None:
    log_file("\n".join(f"2026-10-22 10:00:00 [INFO] kurz {n:04d}" for n in range(500)))

    at = _run()

    shown_lines = _log_text(at).splitlines()
    assert len(shown_lines) == 200
    assert shown_lines[0].endswith("kurz 0300") and shown_lines[-1].endswith("kurz 0499")


# --- D8: EHAL-Schreibfehler -------------------------------------------------------------


def _write_ehal_error(message: str, fields: list[str]) -> None:
    from integrations.ehal_live_records import persist_write_error

    persist_write_error(
        {
            "schema_version": 4,
            "ts": "2026-10-22T10:00:00+02:00",
            "adapter_id": "test_adapter",
            "failed_fields": fields,
            "message": message,
            "retryable": True,
        }
    )


def test_d8_ehal_write_error_shows_warning_with_fields(fake_daemon) -> None:
    _write_ehal_error("Modbus timeout", ["set_ess_mode", "set_evcs_max_current"])

    at = _run()

    assert (
        "EHAL Schreibfehler: Modbus timeout (set_ess_mode, set_evcs_max_current)"
        in messages(at)["warning"]
    )


def test_d8_no_write_error_file_shows_no_warning(fake_daemon) -> None:
    at = _run()

    assert not any("EHAL Schreibfehler" in w for w in messages(at)["warning"])


def test_d8_page_does_not_change_the_error_file(fake_daemon) -> None:
    from integrations.ehal_live_records import write_error_path

    _write_ehal_error("Modbus timeout", ["set_ess_mode"])
    before = file_snapshot(write_error_path())

    _run()

    assert file_snapshot(write_error_path()) == before
