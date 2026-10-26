# tests/apptest/conftest.py
"""Alle Tests in diesem Ordner sind Streamlit-AppTest-UI-Smoketests.

AppTest führt Seiten *wirklich* aus — Formulare/Selectboxen können beim
Interagieren echte Speicher-Pfade (upsert_scenario & Co.) auslösen. Ein Test,
der z. B. eine Selectbox umschaltet, hätte sonst die geteilten Fixture-Dateien
unter tests/fixtures/backtesting/ überschrieben (siehe Vorfall bei der
Einführung dieser Tests). Diese Fixture kopiert die Config-Fixtures deshalb
für jeden Test in ein isoliertes tmp_path-Verzeichnis, bevor die Seite
rendert.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from runtime_store import optimization_history
from simulation import backtesting_log
from tests.conftest import _reinit_config_offline
from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "backtesting"
_THIS_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items):
    # pytest_collection_modifyitems receives the FULL session item list, not just
    # items under this conftest's directory — must filter by path ourselves,
    # otherwise every test in the suite gets marked "apptest" (and -m apptest
    # then runs almost the whole suite instead of just this folder).
    for item in items:
        if _THIS_DIR in Path(str(item.fspath)).parents:
            item.add_marker("apptest")


@pytest.fixture(autouse=True)
def _isolated_backtesting_config(tmp_path, monkeypatch):
    """Rendert/Interagiert gegen eine Wegwerf-Kopie der Backtesting-Fixtures.

    EARNIE_RUNTIME_PATH zeigt ebenfalls auf tmp_path — ohne das würde ein auf
    dem Rechner tatsächlich vorhandenes runtime/backtesting_log.json (bzw.
    run_state.json) in die Seiten gerendert und die Tests von lokalem
    Produktiv-Zustand statt der Fixtures abhängig machen.

    simulation.backtesting_log._DEFAULT_LOG_DIR und
    runtime_store.optimization_history.RUNTIME_DIR/HISTORY_FILE werden je
    einmal beim ersten Modul-Import ausgewertet (nicht bei jedem Aufruf) —
    sobald irgendein anderer Test vor diesem hier zuerst importiert (in der
    vollen Suite praktisch immer der Fall), zeigt EARNIE_RUNTIME_PATH allein
    ins Leere. Deshalb zusätzlich direkt per monkeypatch.setattr überschreiben
    (gleiches Muster wie tests/test_optimization_history.py).

    Open-Meteo bleibt für den ganzen AppTest gemockt, nicht nur während
    reinit_config(): der Szenario-Explorer baut modeled PV für das
    cons_data-Panel und würde sonst archive-api.open-meteo.com anrufen
    (CI-Timeouts unter pytest --cov=.).
    """
    config_dir = tmp_path / "config"
    shutil.copytree(_FIXTURE_DIR, config_dir, ignore=shutil.ignore_patterns("README.md"))
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.setenv("EARNIE_TARIFFS_PATH", str(config_dir / "tariffs.json"))
    monkeypatch.setenv("EARNIE_HOUSE_PROFILES_PATH", str(config_dir / "house_profiles.json"))
    monkeypatch.setenv(
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(config_dir / "components.json"))
    # Fixture copy of the public catalog plus user_grid_fees.json (user_test_home).
    monkeypatch.setenv("EARNIE_GRID_FEES_PATH", str(config_dir / "grid_fees.json"))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(runtime_dir))
    # Formulare, die Zugangsdaten schreiben (Loxone), dürfen nie die echte .env treffen.
    monkeypatch.setenv("EARNIE_DOTENV_PATH", str(config_dir / ".env"))
    # AppTest läuft im Testprozess: von der Seite gesetzte LOXONE_*-Variablen werden
    # nach dem Test wiederhergestellt (monkeypatch merkt sich den Ausgangszustand).
    for _name in ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS"):
        monkeypatch.setenv(_name, "")  # merkt den Ausgangszustand für den Teardown
        monkeypatch.delenv(_name)

    monkeypatch.setattr(backtesting_log, "_DEFAULT_LOG_DIR", str(runtime_dir))
    monkeypatch.setattr(optimization_history, "RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setattr(
        optimization_history,
        "HISTORY_FILE",
        str(runtime_dir / optimization_history.HISTORY_FILENAME),
    )

    install_open_meteo_climate_mock(monkeypatch)
    _reinit_config_offline()
    yield
    _reinit_config_offline()


# --- Fixtures für die Logiktests (Optimierer-Dienst) --------------------------------------


@pytest.fixture
def fake_daemon(monkeypatch, tmp_path):
    """Ersetzt ``status``/``start``/``stop``/``restart`` der Daemon-Seite durch eine Zustandsmaschine.

    AppTest läuft im Testprozess und das Startskript holt das Seitenmodul aus
    ``sys.modules``; so sind die Buttons klickbar, ohne dass ``main.py`` startet.
    """
    from dataclasses import dataclass, field

    from runtime_store.main_daemon import DaemonError, DaemonStatus
    from ui.pages import page_daemon

    @dataclass
    class FakeDaemon:
        state: str = "stopped"
        lock_path: str = ""
        fail_with: str | None = None
        calls: list[str] = field(default_factory=list)

        def status(self):
            pid = 4242 if self.state == "running" else None
            return DaemonStatus(self.state, pid, self.lock_path)

        def _act(self, name, new_state, **_):
            self.calls.append(name)
            if self.fail_with:
                raise DaemonError(self.fail_with)
            self.state = new_state
            return self.status()

        def start(self, **kw):
            return self._act("start", "running", **kw)

        def stop(self, **kw):
            return self._act("stop", "stopped", **kw)

        def restart(self, **kw):
            return self._act("restart", "running", **kw)

    fake = FakeDaemon(lock_path=str(tmp_path / "main.lock"))
    for name in ("status", "start", "stop", "restart"):
        monkeypatch.setattr(page_daemon, name, getattr(fake, name))
    return fake


@pytest.fixture
def local_settings(tmp_path, monkeypatch):
    """Isolierte ``local_settings.json`` (Silent-Schalter); Konfiguration wird neu initialisiert."""
    path = tmp_path / "local_settings.json"
    monkeypatch.setenv("EARNIE_LOCAL_SETTINGS_PATH", str(path))
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    # Die Konfiguration liest den Pfad beim (Re-)Init; ohne Neuinit sieht is_silent_mode()
    # die Datei nicht und der Schalter würde endlos neu schreiben.
    _reinit_config_offline()
    return path


@pytest.fixture
def shadow_mode(monkeypatch, local_settings):
    """``EARNIE_SHADOW=1`` mit isolierter ``local_settings.json``."""
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    _reinit_config_offline()
    return local_settings


@pytest.fixture
def log_file():
    """Fabrik: schreibt ``earnie.log`` in den isolierten Runtime-Pfad und liefert den Pfad.

    ``log_file(text)`` schreibt Text (oder Bytes); ohne Aufruf bleibt die Datei absent.
    """
    from pathlib import Path

    from runtime_store.persist_paths import log_file as log_file_path

    path = Path(log_file_path())

    def _write(content: str | bytes = "") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    _write.path = path  # type: ignore[attr-defined]
    return _write

