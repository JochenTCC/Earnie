# tests/test_greenfield_bootstrap.py
"""Smoke-Tests für Greenfield-Ersteinrichtung (Bootstrap + Setup-Übergang)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime_store import bootstrap
from runtime_store import dotenv_io
from runtime_store.dotenv_loader import load_app_dotenv
from runtime_store.persist_paths import (
    default_cons_data_file,
    resolve_local_settings_json_path,
)


def _prepare_greenfield_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", "config/config.json")
    monkeypatch.setenv("ENERGY_OPTIMIZER_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("ENERGY_OPTIMIZER_OFFLINE", raising=False)

    share_dir = tmp_path / "share" / "config"
    share_dir.mkdir(parents=True)
    (share_dir / ".env.example").write_text(
        'LOXONE_USER="name-des-benutzers-in-der-loxone"\n'
        'LOXONE_PASS="Passwort-des-benutzers-in-der-loxone"\n'
        "LOXONE_IP=192.168.178.1\n",
        encoding="utf-8",
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.example.json").write_text(
        json.dumps({"awattar": {"url": "https://greenfield.example"}}),
        encoding="utf-8",
    )
    return tmp_path


def test_greenfield_bootstrap_creates_expected_files(tmp_path, monkeypatch):
    root = _prepare_greenfield_root(tmp_path, monkeypatch)

    bootstrap.run()

    config_json = root / "config" / "config.json"
    dotenv_path = root / "config" / ".env"
    local_settings = Path(resolve_local_settings_json_path())
    cons_data = Path(default_cons_data_file())

    assert config_json.is_file()
    assert dotenv_path.is_file()
    assert local_settings.is_file()
    assert cons_data.is_file()

    cons_lines = cons_data.read_text(encoding="utf-8").strip().splitlines()
    assert len(cons_lines) == 1
    assert cons_lines[0].startswith("timestamp;")

    assert json.loads(local_settings.read_text(encoding="utf-8"))["loxone_silent_mode"] is False

    dotenv_content = dotenv_path.read_text(encoding="utf-8")
    assert "name-des-benutzers-in-der-loxone" in dotenv_content

    for key in ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS"):
        monkeypatch.delenv(key, raising=False)
    load_app_dotenv(override=True)
    assert dotenv_io.needs_loxone_setup() is True


def test_greenfield_setup_completes_after_dotenv_save(tmp_path, monkeypatch):
    root = _prepare_greenfield_root(tmp_path, monkeypatch)
    bootstrap.run()

    dotenv_path = root / "config" / ".env"
    dotenv_path.write_text(
        dotenv_io.format_loxone_dotenv("192.168.178.99", "greenfield", "dev-only"),
        encoding="utf-8",
    )

    monkeypatch.setenv("LOXONE_IP", "192.168.178.99")
    monkeypatch.setenv("LOXONE_USER", "greenfield")
    monkeypatch.setenv("LOXONE_PASS", "dev-only")

    assert dotenv_io.loxone_credentials_configured() is True
    assert dotenv_io.needs_loxone_setup() is False
