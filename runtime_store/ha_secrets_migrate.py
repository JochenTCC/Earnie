"""One-shot migrate ehal.ha base_url/token from config.json into .env (2.6.i)."""
from __future__ import annotations

import copy
import json
import logging
import os

from runtime_store.dotenv_io import read_ha_dotenv_file, upsert_dotenv_keys
from runtime_store.persist_paths import resolve_config_json_path, resolve_dotenv_path

logger = logging.getLogger(__name__)


def _nonempty(value: object) -> str:
    return str(value or "").strip()


def strip_ha_secrets_from_config(config_doc: dict | None) -> tuple[dict, bool]:
    """Remove ``ehal.ha.base_url`` / ``token`` from config (leave sign/entities)."""
    config = copy.deepcopy(config_doc) if isinstance(config_doc, dict) else {}
    ehal = config.get("ehal")
    if not isinstance(ehal, dict):
        return config, False
    ha = ehal.get("ha")
    if not isinstance(ha, dict):
        return config, False
    if "base_url" not in ha and "token" not in ha:
        return config, False
    ha = dict(ha)
    ha.pop("base_url", None)
    ha.pop("token", None)
    ehal = dict(ehal)
    ehal["ha"] = ha
    config["ehal"] = ehal
    return config, True


def migrate_ha_secrets_to_dotenv(
    config_doc: dict | None,
    *,
    write_dotenv: bool = True,
) -> tuple[dict, bool]:
    """
    Move non-empty ``ehal.ha`` URL/token into ``.env`` once, then strip JSON keys.

    Existing ``.env`` values win — JSON secrets are not written over them.
    Returns ``(stripped_config, changed)`` where ``changed`` means config was stripped
    and/or dotenv was updated.
    """
    config = copy.deepcopy(config_doc) if isinstance(config_doc, dict) else {}
    ehal = config.get("ehal") if isinstance(config.get("ehal"), dict) else {}
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    json_url = _nonempty(ha.get("base_url"))
    json_token = _nonempty(ha.get("token"))
    changed = False

    if write_dotenv and (json_url or json_token):
        path = resolve_dotenv_path()
        env_url, env_token = ("", "")
        try:
            if path and os.path.isfile(path):
                env_url, env_token = read_ha_dotenv_file(path)
        except OSError:
            env_url, env_token = ("", "")
        updates: dict[str, str] = {}
        if json_url and not _nonempty(env_url):
            updates["EHAL_HA_BASE_URL"] = json_url
        if json_token and not _nonempty(env_token):
            updates["EHAL_HA_TOKEN"] = json_token
        if updates:
            try:
                upsert_dotenv_keys(updates)
                changed = True
                logger.info(
                    "migrate_ha_secrets_to_dotenv: wrote %s to .env",
                    ", ".join(sorted(updates)),
                )
            except OSError as exc:
                logger.warning(
                    "migrate_ha_secrets_to_dotenv: could not write .env: %s",
                    exc,
                )

    stripped, stripped_changed = strip_ha_secrets_from_config(config)
    if stripped_changed:
        changed = True
    return stripped, changed


def apply_ha_secrets_migration_to_disk() -> bool:
    """
    Load config.json, migrate secrets to .env, persist stripped config if needed.

    Safe to call at startup; no-op when keys already absent.
    """
    from settings.json_io import read_json_dict, write_json_dict

    path = resolve_config_json_path()
    if not os.path.isfile(path):
        return False
    try:
        data = read_json_dict(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    ehal = data.get("ehal") if isinstance(data.get("ehal"), dict) else {}
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    if "base_url" not in ha and "token" not in ha:
        return False
    new_data, changed = migrate_ha_secrets_to_dotenv(data)
    if not changed:
        return False
    try:
        write_json_dict(path, new_data)
    except OSError as exc:
        logger.warning("migrate_ha_secrets_to_dotenv: cannot write %s: %s", path, exc)
        return False
    return True
