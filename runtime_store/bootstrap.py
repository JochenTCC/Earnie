"""
bootstrap.py – Legt fehlende persistente Dateien an (niemals überschreiben).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Callable

from runtime_store.file_metadata import (
    CONS_DATA_PENDING_SCHEMA,
    CONSUMER_STATE_SCHEMA,
    stamp_payload,
)
from runtime_store.persist_paths import (
    cons_data_pending_file,
    consumer_state_file,
    consumption_profiles_file,
    default_cons_data_file,
    flexible_consumer_profiles_file,
    legacy_history_csv_file,
    log_file,
    resolve_config_json_path,
    resolve_config_schema_template_path,
    resolve_config_template_path,
    runtime_dir,
    total_consumption_profiles_file,
)

logger = logging.getLogger(__name__)

_CONS_DATA_HEADER = "timestamp;total_kw;baseload_kw;pv_kw;source\n"
_EMPTY_PROFILE_HEADER = "Month;Weekday;Hour;Consumption\n"


class BootstrapError(RuntimeError):
    pass


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _is_missing_file(path: str) -> bool:
    if os.path.isdir(path):
        raise BootstrapError(
            f"Bootstrap abgebrochen: '{path}' ist ein Verzeichnis, erwartet wird eine Datei. "
            "Bitte den Ordner auf der NAS löschen und Container neu starten."
        )
    return not os.path.isfile(path)


def _create_file_if_missing(path: str, write_content: Callable[[], None]) -> bool:
    if not _is_missing_file(path):
        return False
    _ensure_parent_dir(path)
    write_content()
    logger.info("bootstrap: Datei angelegt: %s", path)
    return True


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def _write_json(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _ensure_directory(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    logger.info("bootstrap: Verzeichnis bereit: %s", path)


def _copy_template_if_missing(dest_path: str, source_path: str, label: str) -> bool:
    if not _is_missing_file(dest_path):
        return False
    if not os.path.isfile(source_path):
        logger.warning(
            "bootstrap: %s fehlt und Vorlage '%s' ist nicht verfügbar.",
            dest_path,
            source_path,
        )
        return False
    _ensure_parent_dir(dest_path)
    shutil.copyfile(source_path, dest_path)
    logger.info("bootstrap: %s aus %s angelegt.", dest_path, label)
    return True


def _bootstrap_config_example() -> bool:
    dest = os.path.join("config", "config.example.json")
    return _copy_template_if_missing(
        dest,
        resolve_config_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_config_schema() -> bool:
    dest = os.path.join("config", "config.schema.json")
    return _copy_template_if_missing(
        dest,
        resolve_config_schema_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_config_json() -> bool:
    config_path = resolve_config_json_path()
    template_path = resolve_config_template_path()
    if not _is_missing_file(config_path):
        return False
    if not os.path.isfile(template_path):
        raise BootstrapError(
            f"Bootstrap abgebrochen: '{config_path}' fehlt und Vorlage '{template_path}' "
            "ist nicht vorhanden."
        )
    _ensure_parent_dir(config_path)
    shutil.copyfile(template_path, config_path)
    logger.info(
        "bootstrap: %s aus %s erstellt – bitte Loxone-Namen und Verbraucher anpassen.",
        config_path,
        template_path,
    )
    return True


def _bootstrap_cons_data_pending() -> bool:
    path = cons_data_pending_file()
    payload = stamp_payload(
        {"samples": [], "last_daily_flush": None},
        schema_version=CONS_DATA_PENDING_SCHEMA,
    )
    return _create_file_if_missing(path, lambda: _write_json(path, payload))


def _bootstrap_consumer_state() -> bool:
    from datetime import date

    state_path = consumer_state_file()
    today = date.today().isoformat()
    payload = stamp_payload(
        {"date": today, "delivered": {}},
        schema_version=CONSUMER_STATE_SCHEMA,
    )
    return _create_file_if_missing(
        state_path,
        lambda: _write_json(state_path, payload),
    )


def _bootstrap_cons_data_csv() -> bool:
    path = default_cons_data_file()
    return _create_file_if_missing(path, lambda: _write_text(path, _CONS_DATA_HEADER))


def _bootstrap_empty_csv(path: str) -> bool:
    return _create_file_if_missing(path, lambda: _write_text(path, _EMPTY_PROFILE_HEADER))


def _bootstrap_log_file() -> bool:
    path = log_file()
    return _create_file_if_missing(path, lambda: _write_text(path, ""))


def run() -> None:
    """Fehlende Laufzeitdateien anlegen; bestehende Dateien bleiben unverändert."""
    _ensure_directory(runtime_dir())
    _ensure_directory(os.path.join("config"))

    created: list[str] = []

    if _bootstrap_config_example():
        created.append(os.path.join("config", "config.example.json"))
    if _bootstrap_config_schema():
        created.append(os.path.join("config", "config.schema.json"))
    if _bootstrap_config_json():
        created.append(resolve_config_json_path())
    if _bootstrap_cons_data_csv():
        created.append(default_cons_data_file())
    if _bootstrap_cons_data_pending():
        created.append(cons_data_pending_file())
    if _bootstrap_consumer_state():
        created.append(consumer_state_file())
    for path_fn in (
        consumption_profiles_file,
        total_consumption_profiles_file,
        flexible_consumer_profiles_file,
        legacy_history_csv_file,
    ):
        if _bootstrap_empty_csv(path_fn()):
            created.append(path_fn())
    if _bootstrap_log_file():
        created.append(log_file())

    if created:
        logger.info("bootstrap: %s neue Datei(en) angelegt.", len(created))
    else:
        logger.debug("bootstrap: alle persistenten Dateien vorhanden.")
