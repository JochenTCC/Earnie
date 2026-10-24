"""Ebene 2: ein echter ``streamlit run app.py`` gegen die isolierte Fixture-Konfiguration.

Die autouse-Fixture aus ``tests/apptest/conftest.py`` kopiert die Fixtures nach ``tmp_path``
und setzt die ``EARNIE_*_PATH``-Variablen im Testprozess; der Server-Prozess erbt sie.
Der Browser kommt von ``pytest-playwright`` (Fixture ``page``); einmalig
``python -m playwright install chromium``.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_START_TIMEOUT_S = 90.0


def pytest_collection_modifyitems(items):
    for item in items:
        if Path(__file__).parent in Path(str(item.fspath)).parents:
            item.add_marker("e2e")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class AppServer:
    """Startet, stoppt und startet ``streamlit run app.py`` neu (gleiche Daten, gleicher Port)."""

    def __init__(self, log_path: Path) -> None:
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._log_path = log_path
        self._proc: subprocess.Popen | None = None

    @property
    def log_path(self) -> Path:
        return self._log_path

    def start(self) -> None:
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        log = open(self._log_path, "ab")
        self._proc = subprocess.Popen(
            [
                sys.executable, "-m", "streamlit", "run", "app.py",
                "--server.port", str(self.port),
                "--server.address", "127.0.0.1",
                "--server.headless", "true",
                "--server.fileWatcherType", "none",
                "--browser.gatherUsageStats", "false",
            ],
            cwd=_REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        self._wait_until_healthy()

    def _wait_until_healthy(self) -> None:
        deadline = time.monotonic() + _START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(f"streamlit beendet sich beim Start, Log: {self._log_path}")
            try:
                with urllib.request.urlopen(f"{self.url}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        raise TimeoutError(f"streamlit antwortet nicht, Log: {self._log_path}")

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)

    def restart(self) -> None:
        self.stop()
        self.start()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


def _print_log_if_failed(request, server: AppServer) -> None:
    report = getattr(request.node, "rep_call", None)
    if report is None or not report.failed:
        return
    log = server.log_path.read_text(encoding="utf-8", errors="replace") if server.log_path.exists() else ""
    print(f"\n----- Streamlit-Server-Log ({server.log_path}) -----\n{log}\n----- Ende Server-Log -----")


@pytest.fixture(autouse=True)
def _browser_diagnostics(request):
    """Sammelt Browser-Console, Seitenfehler und fehlgeschlagene Requests; Ausgabe nur bei Fehlschlag."""
    if "page" not in request.fixturenames:
        yield
        return
    page = request.getfixturevalue("page")
    events: list[str] = []
    page.on("console", lambda m: events.append(f"console.{m.type}: {m.text}"))
    page.on("pageerror", lambda e: events.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: events.append(f"requestfailed: {r.url} ({r.failure})"))
    page.on("response", lambda r: events.append(f"http {r.status}: {r.url}") if r.status >= 400 else None)
    page.on("websocket", lambda ws: (
        events.append(f"websocket open: {ws.url}"),
        ws.on("close", lambda *_: events.append(f"websocket closed: {ws.url}")),
        ws.on("socketerror", lambda err: events.append(f"websocket error: {err}")),
    ))
    yield
    report = getattr(request.node, "rep_call", None)
    if report is not None and report.failed:
        print("\n----- Browser-Diagnose -----\n" + "\n".join(events) + "\n----- Ende Browser-Diagnose -----")


@pytest.fixture
def hub_configured() -> None:
    """Trägt einen OpenEMS-Hub ein, damit Smarthome-Backend, EHAL-Com und Optimierer-Dienst erscheinen."""
    path = Path(os.environ["EARNIE_CONFIG_PATH"])
    config = json.loads(path.read_text(encoding="utf-8"))
    config["ehal"] = {
        "backend": "openems",
        "adapter_id": "openems_test",
        "openems": {"base_url": "http://127.0.0.1:9"},
    }
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def app_server(request, tmp_path):
    """Laufender Server auf einem freien Port; Log unter ``tmp_path`` (bei Fehlschlag ausgegeben)."""
    server = AppServer(tmp_path / "server.log")
    server.start()
    yield server
    server.stop()
    _print_log_if_failed(request, server)


@pytest.fixture
def app_server_with_hub(request, hub_configured, tmp_path):
    """Wie ``app_server``, aber mit konfiguriertem Hub (Optimierer-Dienst in der Navigation)."""
    server = AppServer(tmp_path / "server.log")
    server.start()
    yield server
    server.stop()
    _print_log_if_failed(request, server)
