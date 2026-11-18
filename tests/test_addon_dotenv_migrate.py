"""HA add-on: ``.env`` from ``/config`` and the one-time move from the data volume."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from dotenv import dotenv_values

from runtime_store.addon_dotenv_migrate import migrate_addon_dotenv
from runtime_store.persist_paths import resolve_dotenv_path

_TEMPLATE = (
    'LOXONE_USER="name-des-benutzers-in-der-loxone"\n'
    'LOXONE_PASS="Passwort-des-benutzers-in-der-loxone"\n'
    "LOXONE_IP=192.168.178.1\n"
)


@pytest.fixture
def addon(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """Add-on layout: config on ``/config``, runtime under ``/data/earnie_env``."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text(_TEMPLATE, encoding="utf-8")
    stack = tmp_path / "data" / "earnie_env"
    data_cfg = stack / "config"
    data_cfg.mkdir(parents=True)
    (stack / "runtime").mkdir()
    addon_cfg = tmp_path / "config"
    addon_cfg.mkdir()
    (addon_cfg / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EARNIE_ENV_PATH", str(stack))
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(stack / "runtime"))
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(addon_cfg))
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
    monkeypatch.delenv("EARNIE_DOTENV_PATH", raising=False)
    return data_cfg / ".env", addon_cfg / ".env"


def test_addon_reads_dotenv_next_to_config_json(addon) -> None:
    data_env, config_env = addon
    data_env.write_text("LOXONE_IP=10.0.0.2\n", encoding="utf-8")
    assert Path(resolve_dotenv_path()).resolve() == config_env.resolve()


def test_outside_the_addon_dotenv_path_is_unchanged(addon, monkeypatch) -> None:
    data_env, _config_env = addon
    monkeypatch.delenv("EARNIE_INSTALL_CONTEXT")
    data_env.write_text("LOXONE_IP=10.0.0.2\n", encoding="utf-8")
    assert Path(resolve_dotenv_path()).resolve() == data_env.resolve()
    assert migrate_addon_dotenv() is None
    assert data_env.is_file()


def test_data_volume_values_win_and_template_values_are_ignored(addon, caplog) -> None:
    data_env, config_env = addon
    config_env.write_text(
        "# migrated by run.sh\n"
        'LOXONE_USER="earnie"\n'
        'LOXONE_PASS="old-secret"\n'
        "LOXONE_IP=10.0.0.5\n",
        encoding="utf-8",
    )
    data_env.write_text(
        _TEMPLATE.replace('"Passwort-des-benutzers-in-der-loxone"', '"new-secret"')
        + 'ENTSOE_API_TOKEN="tok"\n'
        + "EMPTY_KEY=\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.INFO, logger="runtime_store.addon_dotenv_migrate"):
        renamed = migrate_addon_dotenv()

    values = dotenv_values(config_env)
    assert values["LOXONE_PASS"] == "new-secret"
    assert values["LOXONE_USER"] == "earnie"
    assert values["LOXONE_IP"] == "10.0.0.5"
    assert values["ENTSOE_API_TOKEN"] == "tok"
    assert "EMPTY_KEY" not in values
    assert config_env.read_text(encoding="utf-8").startswith("# migrated by run.sh\n")
    assert renamed is not None and Path(renamed).is_file()
    assert Path(renamed).name.startswith(".env.migrated-")
    assert not data_env.exists()
    assert "LOXONE_PASS" in caplog.text
    assert "new-secret" not in caplog.text and "old-secret" not in caplog.text


def test_missing_config_dotenv_is_created_from_the_data_volume(addon) -> None:
    data_env, config_env = addon
    data_env.write_text('EHAL_HA_BASE_URL=http://supervisor/core\nEHAL_HA_TOKEN="t"\n', encoding="utf-8")
    migrate_addon_dotenv()
    values = dotenv_values(config_env)
    assert values["EHAL_HA_BASE_URL"] == "http://supervisor/core"
    assert values["EHAL_HA_TOKEN"] == "t"


def test_migration_runs_once(addon) -> None:
    data_env, config_env = addon
    data_env.write_text("LOXONE_IP=10.0.0.2\n", encoding="utf-8")
    assert migrate_addon_dotenv() is not None
    config_env.write_text("LOXONE_IP=10.0.0.9\n", encoding="utf-8")
    assert migrate_addon_dotenv() is None
    assert dotenv_values(config_env)["LOXONE_IP"] == "10.0.0.9"


def test_template_only_data_dotenv_changes_nothing(addon) -> None:
    data_env, config_env = addon
    original = 'LOXONE_USER="earnie"\nLOXONE_PASS="secret"\nLOXONE_IP=10.0.0.5\n'
    config_env.write_text(original, encoding="utf-8")
    data_env.write_text(_TEMPLATE, encoding="utf-8")
    assert migrate_addon_dotenv() is not None
    assert config_env.read_text(encoding="utf-8") == original


def test_explicit_dotenv_path_skips_the_move(addon, monkeypatch, tmp_path: Path) -> None:
    data_env, _config_env = addon
    data_env.write_text("LOXONE_IP=10.0.0.2\n", encoding="utf-8")
    monkeypatch.setenv("EARNIE_DOTENV_PATH", str(tmp_path / "custom.env"))
    assert migrate_addon_dotenv() is None
    assert data_env.is_file()
