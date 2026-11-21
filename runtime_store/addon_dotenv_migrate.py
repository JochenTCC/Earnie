"""One-time move of the Home Assistant add-on ``.env`` from the data volume to ``/config``.

Up to 2.7 the add-on read ``/data/earnie_env/config/.env`` although its config moved to
``/config`` (``addon_config``): the config migration in ``run.sh`` copied the old ``.env``
along, and bootstrap then created a fresh one from the template on the data volume. Values a
user entered since then are in the data-volume file. From 2.8 the add-on reads ``/config/.env``
(``persist_paths.addon_config_dotenv_path``); this module carries the data-volume values over
once and renames the old file.

Rule (maintainer, 2026-11-18): a value from the data volume wins, because Earnie ran with it.
Empty values and values that equal the template (``.env.example``) are not taken over, so the
template copy that bootstrap created never replaces real credentials. Every key whose value
changes is logged by name only.
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import date

from runtime_store.persist_paths import (
    addon_config_dotenv_path,
    legacy_addon_data_dotenv_path,
    resolve_dotenv_path,
    resolve_dotenv_template_path,
)

logger = logging.getLogger(__name__)


def _values(path: str) -> dict[str, str]:
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path, interpolate=False).items() if v is not None}


def _template_values() -> dict[str, str]:
    template = resolve_dotenv_template_path()
    if not os.path.isfile(template):
        raise FileNotFoundError(
            f".env-Vorlage {template} fehlt; die Add-on-.env kann nicht übernommen werden."
        )
    return _values(template)


def _taken_over(legacy: dict[str, str], template: dict[str, str]) -> dict[str, str]:
    """Data-volume values that count: not empty and not the template's own value."""
    from runtime_store.dotenv_io import _is_placeholder_credential

    return {
        key: value
        for key, value in legacy.items()
        if value.strip()
        and value != template.get(key)
        and not _is_placeholder_credential(key, value.strip())
    }


def _migrated_name(path: str) -> str:
    base = f"{path}.migrated-{date.today():%Y%m%d}"
    candidate, index = base, 1
    while os.path.exists(candidate):
        index += 1
        candidate = f"{base}-{index}"
    return candidate


def migrate_addon_dotenv() -> str | None:
    """Carry the data-volume ``.env`` over to ``/config/.env`` once; return the renamed file.

    ``None`` outside the add-on, when no data-volume ``.env`` exists, or when both paths are
    the same file.
    """
    target = addon_config_dotenv_path()
    if not target:
        return None
    legacy = legacy_addon_data_dotenv_path()
    if not os.path.isfile(legacy):
        return None
    if os.path.abspath(legacy) == os.path.abspath(target):
        return None
    if os.path.abspath(resolve_dotenv_path()) != os.path.abspath(target):
        # EARNIE_DOTENV_PATH names another file: the user chose it, nothing to carry over.
        return None

    from runtime_store.dotenv_io import _atomic_write_dotenv, _merge_dotenv_content, _read_text_file

    updates = _taken_over(_values(legacy), _template_values())
    existing = _values(target) if os.path.isfile(target) else {}
    changed = {key: value for key, value in updates.items() if existing.get(key) != value}
    if changed:
        replaced = sorted(key for key in changed if existing.get(key, "").strip())
        added = sorted(key for key in changed if not existing.get(key, "").strip())
        text = _read_text_file(target) if os.path.isfile(target) else None
        _atomic_write_dotenv(_merge_dotenv_content(text, changed))
        if replaced:
            logger.warning(
                "addon_dotenv: %s aus %s übernommen; dort galt ein anderer Wert als in %s "
                "(Earnie lief mit dem Wert vom Datenvolume).",
                ", ".join(replaced),
                legacy,
                target,
            )
        if added:
            logger.info("addon_dotenv: %s aus %s übernommen.", ", ".join(added), legacy)
    renamed = _migrated_name(legacy)
    shutil.move(legacy, renamed)
    logger.info("addon_dotenv: .env liegt jetzt in %s; alte Datei: %s", target, renamed)
    return renamed
