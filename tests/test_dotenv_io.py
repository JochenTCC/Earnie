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
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    assert dotenv_io.needs_loxone_setup() is False


def test_needs_loxone_setup_deferred_during_planning_onboarding(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.setenv(
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        str(config_dir / "backtesting_scenarios.json"),
    )
    monkeypatch.setenv("EARNIE_COMPONENTS_PATH", str(config_dir / "components.json"))
    monkeypatch.setenv("EARNIE_TARIFFS_PATH", str(config_dir / "tariffs.json"))
    monkeypatch.setenv(
        "EARNIE_HOUSE_PROFILES_PATH",
        str(config_dir / "house_profiles.json"),
    )
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.delenv("LOXONE_USER", raising=False)
    monkeypatch.delenv("LOXONE_PASS", raising=False)
    (config_dir / "config.json").write_text(
        '{"flexible_consumers": [], "live_scenario_id": "live"}',
        encoding="utf-8",
    )
    (config_dir / "components.json").write_text('{"batteries": [], "pv_systems": []}', encoding="utf-8")
    (config_dir / "tariffs.json").write_text(
        '{"import_tariffs": [], "export_tariffs": []}',
        encoding="utf-8",
    )
    (config_dir / "house_profiles.json").write_text('{"profiles": []}', encoding="utf-8")
    (config_dir / "backtesting_scenarios.json").write_text(
        '{"scenarios": [{"id": "live", "settings": {}}]}',
        encoding="utf-8",
    )

    from runtime_store import env_vars

    assert env_vars.is_effective_offline() is True
    assert dotenv_io.loxone_setup_deferred() is True
    assert dotenv_io.needs_loxone_setup() is False
    assert dotenv_io.require_loxone_credentials_for_config() is False


def test_require_loxone_credentials_for_prod_without_onboarding(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
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
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir / "config.json"))
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
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
    monkeypatch.setenv("EARNIE_DOTENV_PATH", "config/.env")

    path = dotenv_io.write_loxone_dotenv("10.0.0.5", "loxuser", 'pa"ss')
    assert path.replace("\\", "/") == "config/.env"
    content = (tmp_path / "config" / ".env").read_text(encoding="utf-8")
    assert 'LOXONE_USER="loxuser"' in content
    assert 'LOXONE_PASS="pa\\"ss"' in content
    assert "LOXONE_IP=10.0.0.5" in content


def test_write_loxone_dotenv_rejects_empty_user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_DOTENV_PATH", "config/.env")
    with pytest.raises(ValueError, match="Benutzername"):
        dotenv_io.write_loxone_dotenv("10.0.0.5", "  ", "secret")


def test_write_loxone_dotenv_preserves_original_when_replace_fails(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    env_path = config_dir / ".env"
    original = 'LOXONE_USER="keep"\nLOXONE_PASS="secret"\nLOXONE_IP=10.0.0.1\n'
    env_path.write_text(original, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_DOTENV_PATH", "config/.env")

    def _fail_replace(src: str, dst: str) -> None:
        raise PermissionError(f"denied: {src} -> {dst}")

    monkeypatch.setattr(os, "replace", _fail_replace)
    with pytest.raises(OSError, match="denied"):
        dotenv_io.write_loxone_dotenv("10.0.0.5", "newuser", "newpass")
    assert env_path.read_text(encoding="utf-8") == original
    assert not (config_dir / ".env.tmp").exists()


def test_write_loxone_dotenv_restores_when_post_replace_content_invalid(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    env_path = config_dir / ".env"
    original = 'LOXONE_USER="keep"\nLOXONE_PASS="secret"\nLOXONE_IP=10.0.0.1\n'
    env_path.write_text(original, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_DOTENV_PATH", "config/.env")

    def _empty_replace(src: str, dst: str) -> None:
        with open(dst, "w", encoding="utf-8"):
            pass
        os.remove(src)

    monkeypatch.setattr(os, "replace", _empty_replace)
    with pytest.raises(OSError, match="wiederhergestellt"):
        dotenv_io.write_loxone_dotenv("10.0.0.5", "newuser", "newpass")
    assert env_path.read_text(encoding="utf-8") == original


def test_loxone_dotenv_conflict_detects_root_mismatch(tmp_path, monkeypatch):
    env_root = tmp_path / "earnie_env" / "config"
    env_root.mkdir(parents=True)
    canonical = env_root / ".env"
    canonical.write_text(
        'LOXONE_USER="user-a"\nLOXONE_PASS="pass-a"\nLOXONE_IP=10.0.0.1\n',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        'LOXONE_USER="user-a"\nLOXONE_PASS="pass-b"\nLOXONE_IP=10.0.0.1\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_ENV_PATH", "earnie_env")

    conflict = dotenv_io.loxone_dotenv_conflict()

    assert conflict is not None
    assert conflict["canonical_path"].replace("\\", "/") == "earnie_env/config/.env"
    assert conflict["conflicts"][0]["path"] == ".env"


def test_import_loxone_dotenv_from_copies_credentials(tmp_path, monkeypatch):
    env_root = tmp_path / "earnie_env" / "config"
    env_root.mkdir(parents=True)
    canonical = env_root / ".env"
    canonical.write_text(
        'LOXONE_USER="old"\nLOXONE_PASS="oldpass"\nLOXONE_IP=10.0.0.1\n',
        encoding="utf-8",
    )
    source = tmp_path / ".env"
    source.write_text(
        'LOXONE_USER="new"\nLOXONE_PASS="newpass"\nLOXONE_IP=10.0.0.2\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_ENV_PATH", "earnie_env")

    written = dotenv_io.import_loxone_dotenv_from(".env")

    assert written.replace("\\", "/") == "earnie_env/config/.env"
    ip, user, password = dotenv_io.read_loxone_dotenv_file(str(canonical))
    assert (ip, user, password) == ("10.0.0.2", "new", "newpass")
