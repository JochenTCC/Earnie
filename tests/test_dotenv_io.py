# tests/test_dotenv_io.py
from __future__ import annotations

import os

import pytest

from runtime_store import dotenv_io


def test_loxone_credentials_configured_false_when_missing(monkeypatch):
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.delenv("LOXONE_USER", raising=False)
    monkeypatch.delenv("LOXONE_PASS", raising=False)
    assert dotenv_io.loxone_credentials_configured() is False


def test_loxone_credentials_configured_false_for_placeholders(monkeypatch):
    monkeypatch.setenv("LOXONE_IP", "192.168.178.10")
    monkeypatch.setenv("LOXONE_USER", "name-des-benutzers-in-der-loxone")
    monkeypatch.setenv("LOXONE_PASS", "Passwort-des-benutzers-in-der-loxone")
    assert dotenv_io.loxone_credentials_configured() is False


def test_loxone_credentials_configured_true_when_complete(monkeypatch):
    monkeypatch.setenv("LOXONE_IP", "192.168.178.10")
    monkeypatch.setenv("LOXONE_USER", "admin")
    monkeypatch.setenv("LOXONE_PASS", "secret")
    assert dotenv_io.loxone_credentials_configured() is True


def test_needs_loxone_setup_respects_offline(monkeypatch):
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    assert dotenv_io.needs_loxone_setup() is False


def test_needs_loxone_setup_deferred_during_planning_onboarding(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.delenv("ENERGY_OPTIMIZER_OFFLINE", raising=False)
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.delenv("LOXONE_USER", raising=False)
    monkeypatch.delenv("LOXONE_PASS", raising=False)
    (config_dir / "config.json").write_text(
        '{"flexible_consumers": [], "batteries": [], "pv_systems": []}',
        encoding="utf-8",
    )

    assert dotenv_io.loxone_setup_deferred() is True
    assert dotenv_io.needs_loxone_setup() is False
    assert dotenv_io.require_loxone_credentials_for_config() is False


def test_require_loxone_credentials_for_prod_without_onboarding(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.delenv("ENERGY_OPTIMIZER_OFFLINE", raising=False)
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.delenv("LOXONE_USER", raising=False)
    monkeypatch.delenv("LOXONE_PASS", raising=False)
    (config_dir / "config.json").write_text(
        '{"flexible_consumers": [{"id": "swimspa"}]}',
        encoding="utf-8",
    )

    assert dotenv_io.loxone_setup_deferred() is True
    assert dotenv_io.require_loxone_credentials_for_config() is False


def test_loxone_setup_not_deferred_when_betrieb_unlocked(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.delenv("ENERGY_OPTIMIZER_OFFLINE", raising=False)
    (config_dir / "config.json").write_text(
        '{"flexible_consumers": [{"id": "swimspa"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr("ui.setup_readiness._loxone_markers_complete", lambda: True)

    assert dotenv_io.loxone_setup_deferred() is False
    assert dotenv_io.require_loxone_credentials_for_config() is True


def test_validate_loxone_ip_rejects_invalid():
    assert dotenv_io.validate_loxone_ip("") == "IP-Adresse ist erforderlich."
    assert dotenv_io.validate_loxone_ip("not-an-ip") is not None


def test_write_loxone_dotenv_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_DOTENV_PATH", "config/.env")

    path = dotenv_io.write_loxone_dotenv("10.0.0.5", "loxuser", 'pa"ss')
    assert path.replace("\\", "/") == "config/.env"
    content = (tmp_path / "config" / ".env").read_text(encoding="utf-8")
    assert 'LOXONE_USER="loxuser"' in content
    assert 'LOXONE_PASS="pa\\"ss"' in content
    assert "LOXONE_IP=10.0.0.5" in content


def test_write_loxone_dotenv_rejects_empty_user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENERGY_OPTIMIZER_DOTENV_PATH", "config/.env")
    with pytest.raises(ValueError, match="Benutzername"):
        dotenv_io.write_loxone_dotenv("10.0.0.5", "  ", "secret")
