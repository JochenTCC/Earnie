# tests/test_ha_secrets_migrate.py
from __future__ import annotations

import json

from runtime_store import ha_secrets_migrate


def test_migrate_ha_secrets_writes_dotenv_and_strips_json(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_DOTENV_PATH", "config/.env")

    config = {
        "ehal": {
            "backend": "ha",
            "ha": {
                "base_url": "http://homeassistant:8123",
                "token": "secret-token",
                "sign": {"sens_ess_power": "ehal"},
                "entities": {},
            },
        }
    }
    new_config, changed = ha_secrets_migrate.migrate_ha_secrets_to_dotenv(config)
    assert changed is True
    ha = new_config["ehal"]["ha"]
    assert "base_url" not in ha
    assert "token" not in ha
    assert ha["sign"]["sens_ess_power"] == "ehal"
    env_path = config_dir / ".env"
    content = env_path.read_text(encoding="utf-8")
    assert "EHAL_HA_BASE_URL=http://homeassistant:8123" in content
    assert 'EHAL_HA_TOKEN="secret-token"' in content


def test_migrate_prefers_existing_dotenv_over_json(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / ".env").write_text(
        "EHAL_HA_BASE_URL=http://from-env:8123\nEHAL_HA_TOKEN=\"env-tok\"\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_DOTENV_PATH", "config/.env")

    config = {
        "ehal": {
            "ha": {
                "base_url": "http://from-json:8123",
                "token": "json-tok",
            }
        }
    }
    new_config, changed = ha_secrets_migrate.migrate_ha_secrets_to_dotenv(config)
    assert changed is True
    content = (config_dir / ".env").read_text(encoding="utf-8")
    assert "http://from-env:8123" in content
    assert "env-tok" in content
    assert "from-json" not in content
    assert "base_url" not in new_config["ehal"]["ha"]


def test_apply_ha_secrets_migration_to_disk(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "ehal": {
                    "backend": "ha",
                    "ha": {
                        "base_url": "http://ha:8123",
                        "token": "disk-tok",
                        "sign": {},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("EARNIE_DOTENV_PATH", str(tmp_path / ".env"))

    assert ha_secrets_migrate.apply_ha_secrets_migration_to_disk() is True
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert "base_url" not in data["ehal"]["ha"]
    assert "token" not in data["ehal"]["ha"]
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "EHAL_HA_BASE_URL=http://ha:8123" in content
    assert 'EHAL_HA_TOKEN="disk-tok"' in content
    assert ha_secrets_migrate.apply_ha_secrets_migration_to_disk() is False
