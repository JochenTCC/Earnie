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
    config_dir,
    config_path,
    cons_data_pending_file,
    consumer_state_file,
    consumption_profiles_file,
    default_cons_data_file,
    flexible_consumer_profiles_file,
    legacy_history_csv_file,
    log_file,
    resolve_backtesting_scenarios_json_path,
    resolve_backtesting_scenarios_minimal_template_path,
    resolve_backtesting_scenarios_schema_template_path,
    resolve_backtesting_scenarios_template_path,
    resolve_components_json_path,
    resolve_components_minimal_template_path,
    resolve_components_schema_template_path,
    resolve_components_template_path,
    resolve_house_profiles_json_path,
    resolve_house_profiles_minimal_template_path,
    resolve_house_profiles_schema_template_path,
    resolve_house_profiles_template_path,
    resolve_tariffs_catalog_template_path,
    resolve_tariffs_json_path,
    resolve_tariffs_minimal_template_path,
    resolve_tariffs_schema_template_path,
    resolve_tariffs_template_path,
    resolve_config_json_path,
    resolve_config_minimal_template_path,
    resolve_config_schema_template_path,
    resolve_config_template_path,
    resolve_deviation_rules_json_path,
    resolve_deviation_rules_schema_template_path,
    resolve_deviation_rules_template_path,
    resolve_dotenv_path,
    resolve_dotenv_template_path,
    resolve_local_settings_json_path,
    resolve_local_settings_template_path,
    runtime_dir,
    total_consumption_profiles_file,
)

_LEGACY_DOTENV = ".env"

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
    dest = config_path("config.example.json")
    return _copy_template_if_missing(
        dest,
        resolve_config_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_config_schema() -> bool:
    dest = config_path("config.schema.json")
    return _copy_template_if_missing(
        dest,
        resolve_config_schema_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_config_json() -> bool:
    config_path = resolve_config_json_path()
    template_path = resolve_config_minimal_template_path()
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
        "bootstrap: %s aus %s erstellt – Hausdaten im Hauskonfigurator und in der Konfiguration anlegen.",
        config_path,
        template_path,
    )
    return True


def _bootstrap_backtesting_scenarios_example() -> bool:
    dest = config_path("backtesting_scenarios.example.json")
    return _copy_template_if_missing(
        dest,
        resolve_backtesting_scenarios_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_backtesting_scenarios_schema() -> bool:
    dest = config_path("backtesting_scenarios.schema.json")
    return _copy_template_if_missing(
        dest,
        resolve_backtesting_scenarios_schema_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_backtesting_scenarios_json() -> bool:
    scenarios_path = resolve_backtesting_scenarios_json_path()
    template_path = resolve_backtesting_scenarios_minimal_template_path()
    return _copy_template_if_missing(
        scenarios_path,
        template_path,
        "backtesting_scenarios.minimal.json",
    )


def _bootstrap_tariffs_example() -> bool:
    dest = config_path("tariffs.example.json")
    return _copy_template_if_missing(
        dest,
        resolve_tariffs_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_tariffs_schema() -> bool:
    dest = config_path("tariffs.schema.json")
    return _copy_template_if_missing(
        dest,
        resolve_tariffs_schema_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_tariffs_json() -> bool:
    """Seed site tariffs.json from public catalog, else example, else minimal."""
    dest = resolve_tariffs_json_path()
    catalog = resolve_tariffs_catalog_template_path()
    if os.path.isfile(catalog) and os.path.normpath(catalog) != os.path.normpath(dest):
        return _copy_template_if_missing(dest, catalog, "share/config/tariffs.json")
    example = resolve_tariffs_template_path()
    if os.path.isfile(example) and os.path.normpath(example) != os.path.normpath(dest):
        return _copy_template_if_missing(dest, example, "tariffs.example.json")
    return _copy_template_if_missing(
        dest,
        resolve_tariffs_minimal_template_path(),
        "tariffs.minimal.json",
    )


def _bootstrap_house_profiles_example() -> bool:
    dest = config_path("house_profiles.example.json")
    return _copy_template_if_missing(
        dest,
        resolve_house_profiles_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_house_profiles_schema() -> bool:
    dest = config_path("house_profiles.schema.json")
    return _copy_template_if_missing(
        dest,
        resolve_house_profiles_schema_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_house_profiles_json() -> bool:
    return _copy_template_if_missing(
        resolve_house_profiles_json_path(),
        resolve_house_profiles_minimal_template_path(),
        "house_profiles.minimal.json",
    )


def _bootstrap_components_example() -> bool:
    dest = config_path("components.example.json")
    return _copy_template_if_missing(
        dest,
        resolve_components_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_components_schema() -> bool:
    dest = config_path("components.schema.json")
    return _copy_template_if_missing(
        dest,
        resolve_components_schema_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_components_json() -> bool:
    return _copy_template_if_missing(
        resolve_components_json_path(),
        resolve_components_minimal_template_path(),
        "components.minimal.json",
    )


def _bootstrap_deviation_rules_example() -> bool:
    dest = config_path("deviation_rules.example.json")
    return _copy_template_if_missing(
        dest,
        resolve_deviation_rules_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_deviation_rules_schema() -> bool:
    dest = config_path("deviation_rules.schema.json")
    return _copy_template_if_missing(
        dest,
        resolve_deviation_rules_schema_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_deviation_rules_json() -> bool:
    rules_path = resolve_deviation_rules_json_path()
    template_path = resolve_deviation_rules_template_path()
    return _copy_template_if_missing(
        rules_path,
        template_path,
        "deviation_rules.example.json",
    )


def _bootstrap_local_settings_json() -> bool:
    settings_path = resolve_local_settings_json_path()
    template_path = resolve_local_settings_template_path()
    if not _is_missing_file(settings_path):
        return False
    if os.path.isfile(template_path):
        _ensure_parent_dir(settings_path)
        shutil.copyfile(template_path, settings_path)
        logger.info(
            "bootstrap: %s aus %s angelegt.",
            settings_path,
            template_path,
        )
        return True
    return _create_file_if_missing(
        settings_path,
        lambda: _write_json(settings_path, {"loxone_silent_mode": False}),
    )


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


def _warn_legacy_dotenv_directory() -> None:
    if os.path.isdir(_LEGACY_DOTENV):
        logger.error(
            "bootstrap: './.env' ist ein Verzeichnis (typisch nach fehlgeschlagenem "
            "Docker-Bind-Mount). Bitte auf dem Host löschen: rm -rf .env"
        )


def _bootstrap_dotenv() -> bool:
    _warn_legacy_dotenv_directory()
    canonical = resolve_dotenv_path()
    if not _is_missing_file(canonical):
        return False
    if os.path.isfile(_LEGACY_DOTENV) and canonical != _LEGACY_DOTENV:
        _ensure_parent_dir(canonical)
        shutil.copyfile(_LEGACY_DOTENV, canonical)
        logger.info(
            "bootstrap: %s aus Legacy %s migriert – bitte Loxone-Zugangsdaten prüfen.",
            canonical,
            _LEGACY_DOTENV,
        )
        return True
    template_path = resolve_dotenv_template_path()
    return _copy_template_if_missing(
        canonical,
        template_path,
        ".env.example",
    )


def run() -> None:
    """Fehlende Laufzeitdateien anlegen; bestehende Dateien bleiben unverändert."""
    _ensure_directory(runtime_dir())
    _ensure_directory(config_dir())

    created: list[str] = []

    if _bootstrap_config_example():
        created.append(config_path("config.example.json"))
    if _bootstrap_config_schema():
        created.append(config_path("config.schema.json"))
    if _bootstrap_config_json():
        created.append(resolve_config_json_path())
    if _bootstrap_backtesting_scenarios_example():
        created.append(config_path("backtesting_scenarios.example.json"))
    if _bootstrap_backtesting_scenarios_schema():
        created.append(config_path("backtesting_scenarios.schema.json"))
    if _bootstrap_backtesting_scenarios_json():
        created.append(resolve_backtesting_scenarios_json_path())
    if _bootstrap_tariffs_example():
        created.append(config_path("tariffs.example.json"))
    if _bootstrap_tariffs_schema():
        created.append(config_path("tariffs.schema.json"))
    if _bootstrap_tariffs_json():
        created.append(resolve_tariffs_json_path())
    if _bootstrap_house_profiles_example():
        created.append(config_path("house_profiles.example.json"))
    if _bootstrap_house_profiles_schema():
        created.append(config_path("house_profiles.schema.json"))
    if _bootstrap_house_profiles_json():
        created.append(resolve_house_profiles_json_path())
    if _bootstrap_components_example():
        created.append(config_path("components.example.json"))
    if _bootstrap_components_schema():
        created.append(config_path("components.schema.json"))
    if _bootstrap_components_json():
        created.append(resolve_components_json_path())
    if _bootstrap_deviation_rules_example():
        created.append(config_path("deviation_rules.example.json"))
    if _bootstrap_deviation_rules_schema():
        created.append(config_path("deviation_rules.schema.json"))
    if _bootstrap_deviation_rules_json():
        created.append(resolve_deviation_rules_json_path())
    if _bootstrap_local_settings_json():
        created.append(resolve_local_settings_json_path())
    if _bootstrap_dotenv():
        created.append(resolve_dotenv_path())
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

    from runtime_store.offline_demo_seed import seed_offline_live_scenario

    if seed_offline_live_scenario():
        logger.info("bootstrap: offline demo live-scenario refs seeded.")
