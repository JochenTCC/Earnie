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

from tests.conftest import _reinit_config_offline

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
    """Rendert/Interagiert gegen eine Wegwerf-Kopie der Backtesting-Fixtures."""
    config_dir = tmp_path / "config"
    shutil.copytree(_FIXTURE_DIR, config_dir, ignore=shutil.ignore_patterns("README.md"))

    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.setenv("EARNIE_TARIFFS_PATH", str(config_dir / "tariffs.json"))
    monkeypatch.setenv("EARNIE_HOUSE_PROFILES_PATH", str(config_dir / "house_profiles.json"))
    monkeypatch.setenv(
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(config_dir / "components.json"))

    _reinit_config_offline()
    yield
    _reinit_config_offline()
