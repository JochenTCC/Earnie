"""UI-Verifikation Issue #50: "Jetzt neu berechnen" (Optimierer-Dienst) und Warnung bei
``settlement_fee_cent_kwh`` an Fix-/Monatstarifen (Szenarienkonfigurator lädt den Katalog).

Die Daemon-Seite läuft gegen ``fake_daemon``. Der Button-Test am Ende spricht über echtes
HTTP mit einem Wegwerf-Listener, nicht mit ``main.py``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from house_config import tariffs_store
from integrations.ehal_request_http import REQUEST_OPTIMIZE_PATH
from runtime_store import optimize_request
from runtime_store.optimize_request import OptimizeRequestError
from tests.apptest.helpers import assert_clean, click, messages
from ui.pages import page_daemon

_DAEMON_SCRIPT = Path(__file__).parent / "scripts" / "run_page_daemon.py"
_EDITOR_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"
_TIMEOUT_S = 30.0
_BUTTON = "daemon_recompute"
_CONFIRMATION = "Neuberechnung angefordert."


def _run_daemon_page() -> AppTest:
    at = AppTest.from_file(str(_DAEMON_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert_clean(at)
    return at


# --- #50/3: Button "Jetzt neu berechnen" ------------------------------------------------


def test_recompute_disabled_when_daemon_stopped(fake_daemon, monkeypatch) -> None:
    fake_daemon.state = "stopped"
    monkeypatch.setattr(page_daemon, "plan_inputs_changed_since_last_run", lambda: True)

    at = _run_daemon_page()

    assert at.button(key=_BUTTON).disabled is True


def test_recompute_disabled_when_no_plan_input_changed(fake_daemon, monkeypatch) -> None:
    fake_daemon.state = "running"
    monkeypatch.setattr(page_daemon, "plan_inputs_changed_since_last_run", lambda: False)

    at = _run_daemon_page()

    assert at.button(key=_BUTTON).disabled is True


def test_recompute_enabled_click_requests_once_and_confirms(fake_daemon, monkeypatch) -> None:
    fake_daemon.state = "running"
    calls: list[str] = []
    monkeypatch.setattr(page_daemon, "plan_inputs_changed_since_last_run", lambda: True)
    monkeypatch.setattr(page_daemon, "request_optimize", lambda: calls.append("request"))

    at = _run_daemon_page()
    assert at.button(key=_BUTTON).disabled is False
    at = click(at, _BUTTON)

    assert_clean(at)
    assert calls == ["request"]
    assert _CONFIRMATION in messages(at)["success"]
    assert not at.error


def test_recompute_unreachable_daemon_shows_error_not_exception(fake_daemon, monkeypatch) -> None:
    fake_daemon.state = "running"
    monkeypatch.setattr(page_daemon, "plan_inputs_changed_since_last_run", lambda: True)

    def _fail() -> None:
        raise OptimizeRequestError("Optimierer-Dienst unter Port 1 nicht erreichbar (x).")

    monkeypatch.setattr(page_daemon, "request_optimize", _fail)

    at = click(_run_daemon_page(), _BUTTON)

    assert_clean(at)
    assert messages(at)["error"] == ["Optimierer-Dienst unter Port 1 nicht erreichbar (x)."]
    assert _CONFIRMATION not in messages(at)["success"]


def _plan_input_state(tmp_path: Path, *, file_newer_than_run: bool) -> tuple[dict, tuple]:
    """Echte mtime-Logik: Run-State plus eine Konfigurationsdatei vor/nach dem Lauf."""
    from datetime import datetime, timezone

    config_file = tmp_path / "tariffs_probe.json"
    config_file.write_text("{}", encoding="utf-8")
    run_epoch = time.time() - 600
    file_epoch = run_epoch + 300 if file_newer_than_run else run_epoch - 300
    os.utime(config_file, (file_epoch, file_epoch))
    state = {"completed_at": datetime.fromtimestamp(run_epoch, timezone.utc).isoformat()}
    return state, (lambda: str(config_file),)


@pytest.mark.parametrize("newer,expect_disabled", [(True, False), (False, True)])
def test_recompute_follows_real_mtime_logic(
    fake_daemon, monkeypatch, tmp_path, newer: bool, expect_disabled: bool
) -> None:
    fake_daemon.state = "running"
    state, resolvers = _plan_input_state(tmp_path, file_newer_than_run=newer)
    monkeypatch.setattr(
        page_daemon,
        "plan_inputs_changed_since_last_run",
        lambda: optimize_request.plan_inputs_changed_since_last_run(state, resolvers=resolvers),
    )

    at = _run_daemon_page()

    assert at.button(key=_BUTTON).disabled is expect_disabled


def test_recompute_click_posts_to_the_daemon_listener(fake_daemon, monkeypatch) -> None:
    """Ende-zu-Ende: Klick -> echter HTTP-POST auf die Request-Optimize-Route."""
    received: list[tuple[str, str]] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            received.append((self.command, self.path))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(optimize_request.config, "get_ehal_http_port", lambda: server.server_port)
        monkeypatch.setattr(page_daemon, "plan_inputs_changed_since_last_run", lambda: True)
        fake_daemon.state = "running"

        at = click(_run_daemon_page(), _BUTTON)
    finally:
        server.shutdown()
        server.server_close()

    assert_clean(at)
    assert received == [("POST", REQUEST_OPTIMIZE_PATH)]
    assert _CONFIRMATION in messages(at)["success"]


# --- #50/1: settlement_fee_cent_kwh an Fixtarif -----------------------------------------


@pytest.fixture
def fixed_tariff_with_fee() -> str:
    """Hängt einen Fixtarif mit Abwicklungsgebühr an den isolierten Katalog; liefert dessen Label."""
    path = Path(os.environ["EARNIE_TARIFFS_PATH"])
    doc = json.loads(path.read_text(encoding="utf-8"))
    label = "Fix mit Gebühr (Test)"
    doc["import_tariffs"].append(
        {
            "id": "fixed_with_fee",
            "label": label,
            "type": "fixed_cent",
            "land": "AT",
            "fix_cent_kwh": 12.0,
            "settlement_fee_cent_kwh": 9.08,
            "prices_include_vat": False,
            "vat_percent": 20.0,
            "supplier_id": "test",
        }
    )
    path.write_text(json.dumps(doc), encoding="utf-8")
    tariffs_store._warned_ignored_settlement_fee.clear()
    return label


def _fee_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "settlement_fee_cent_kwh" in r.getMessage()]


def test_scenario_editor_loads_fixed_tariff_with_fee_and_warns_once(
    fixed_tariff_with_fee: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=tariffs_store.logger.name):
        at = AppTest.from_file(str(_EDITOR_SCRIPT)).run(timeout=_TIMEOUT_S)
        assert_clean(at)
        at.run(timeout=_TIMEOUT_S)  # zweiter Lauf: pro Tarif nur eine Warnung
        assert_clean(at)

    records = _fee_warnings(caplog)
    assert len(records) == 1
    text = records[0].getMessage()
    assert "fixed_with_fee" in text and "netznutzung" in text
    assert fixed_tariff_with_fee in next(sb for sb in at.selectbox if sb.label == "Bezugstarif").options


def test_scenario_editor_spot_tariff_fee_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    tariffs_store._warned_ignored_settlement_fee.clear()
    with caplog.at_level(logging.WARNING, logger=tariffs_store.logger.name):
        assert_clean(AppTest.from_file(str(_EDITOR_SCRIPT)).run(timeout=_TIMEOUT_S))

    assert _fee_warnings(caplog) == []
