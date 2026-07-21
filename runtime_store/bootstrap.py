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
    bundled_backtesting_scenarios_schema_file,
    bundled_components_schema_file,
    bundled_config_schema_file,
    bundled_deviation_rules_schema_file,
    bundled_house_profiles_schema_file,
    bundled_tariffs_schema_file,
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


def _read_schema_data_model_const(schema_doc: dict) -> int | None:
    props = schema_doc.get("properties")
    if not isinstance(props, dict):
        return None
    model = props.get("earnie_data_model")
    if not isinstance(model, dict):
        return None
    const = model.get("const")
    if const is None:
        return None
    try:
        return int(const)
    except (TypeError, ValueError):
        return None


def _copy_schema_if_missing_or_stale(
    dest_path: str,
    bundled_source_path: str,
    label: str,
) -> bool:
    """Create or upgrade site *.schema.json when bundled earnie_data_model const is newer."""
    if not os.path.isfile(bundled_source_path):
        if _is_missing_file(dest_path):
            logger.warning(
                "bootstrap: %s fehlt und Vorlage '%s' ist nicht verfügbar.",
                dest_path,
                bundled_source_path,
            )
        return False

    from settings.json_io import read_json_dict

    bundled = read_json_dict(bundled_source_path)
    bundled_const = _read_schema_data_model_const(bundled)

    if _is_missing_file(dest_path):
        _ensure_parent_dir(dest_path)
        shutil.copyfile(bundled_source_path, dest_path)
        logger.info("bootstrap: %s aus %s angelegt.", dest_path, label)
        return True

    if bundled_const is None:
        return False

    local = read_json_dict(dest_path)
    local_const = _read_schema_data_model_const(local)
    if local_const is not None and local_const >= bundled_const:
        return False

    shutil.copyfile(bundled_source_path, dest_path)
    logger.info(
        "bootstrap: %s aus %s aktualisiert (Schema earnie_data_model %s → %s).",
        dest_path,
        label,
        local_const,
        bundled_const,
    )
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
    return _copy_schema_if_missing_or_stale(
        dest,
        bundled_config_schema_file(),
        "share/config/config.schema.json",
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
    return _copy_schema_if_missing_or_stale(
        dest,
        bundled_backtesting_scenarios_schema_file(),
        "share/config/backtesting_scenarios.schema.json",
    )


def _bootstrap_backtesting_scenarios_json() -> bool:
    scenarios_path = resolve_backtesting_scenarios_json_path()
    template_path = resolve_backtesting_scenarios_minimal_template_path()
    return _copy_template_if_missing(
        scenarios_path,
        template_path,
        "backtesting_scenarios.minimal.json",
    )


_OEMAG_SHARED_TARIFF_KEYS = (
    "oemag_monthly_feed_in_rates",
    "monthly_float_reference_cent_kwh",
    "econtrol_referenzmarktwert_pv_monthly",
)
_OEMAG_DATA_MODEL_V2 = 2


def _oemag_rates_template_doc() -> dict:
    """Source for missing OeMAG keys: tariffs minimal template, else example."""
    from settings.json_io import read_json_dict

    for path in (
        resolve_tariffs_minimal_template_path(),
        resolve_tariffs_template_path(),
    ):
        if not os.path.isfile(path):
            continue
        doc = read_json_dict(path)
        if all(key in doc for key in _OEMAG_SHARED_TARIFF_KEYS):
            return doc
    return {}


def _read_data_model_version(doc: dict) -> int:
    raw = doc.get("earnie_data_model")
    if raw is None:
        return 1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def _migrate_oemag_data_model_v2() -> list[str]:
    """
    Convert earnie_data_model 1 → 2 for tariffs + backtesting_scenarios.

    - Copy OeMAG reference keys from scenarios to tariffs when missing there.
    - Strip legacy OeMAG keys from scenarios.
    - Template-fill tariffs if keys are still absent.
    - Stamp both documents to earnie_data_model=2 when changed or still < 2.
    """
    tariffs_path = resolve_tariffs_json_path()
    if not os.path.isfile(tariffs_path):
        return []
    from settings.json_io import read_json_dict, write_json_dict

    scenarios_path = resolve_backtesting_scenarios_json_path()
    tariffs = read_json_dict(tariffs_path)
    scenarios: dict | None = None
    if os.path.isfile(scenarios_path):
        scenarios = read_json_dict(scenarios_path)

    tariffs_changed = False
    scenarios_changed = False
    copied: list[str] = []
    stripped: list[str] = []
    filled: list[str] = []

    if scenarios is not None:
        for key in _OEMAG_SHARED_TARIFF_KEYS:
            if scenarios.get(key) is None:
                continue
            if tariffs.get(key) is None:
                tariffs[key] = scenarios[key]
                tariffs_changed = True
                copied.append(key)
            if key in scenarios:
                del scenarios[key]
                scenarios_changed = True
                stripped.append(key)

    missing = [key for key in _OEMAG_SHARED_TARIFF_KEYS if tariffs.get(key) is None]
    if missing:
        template = _oemag_rates_template_doc()
        for key in missing:
            if key in template:
                tariffs[key] = template[key]
                tariffs_changed = True
                filled.append(key)

    if _read_data_model_version(tariffs) < _OEMAG_DATA_MODEL_V2 or tariffs_changed:
        tariffs["earnie_data_model"] = _OEMAG_DATA_MODEL_V2
        tariffs_changed = True
    if scenarios is not None and (
        _read_data_model_version(scenarios) < _OEMAG_DATA_MODEL_V2 or scenarios_changed
    ):
        scenarios["earnie_data_model"] = _OEMAG_DATA_MODEL_V2
        scenarios_changed = True

    modified: list[str] = []
    if tariffs_changed:
        write_json_dict(tariffs_path, tariffs)
        modified.append(tariffs_path)
    if scenarios is not None and scenarios_changed:
        write_json_dict(scenarios_path, scenarios)
        modified.append(scenarios_path)

    if copied or stripped or filled:
        logger.info(
            "bootstrap: OeMAG data-model v2 migration "
            "(copied=%s, stripped=%s, filled=%s) → %s",
            ",".join(copied) or "-",
            ",".join(stripped) or "-",
            ",".join(filled) or "-",
            ", ".join(modified),
        )
    elif modified:
        logger.info(
            "bootstrap: stamped earnie_data_model=2 on %s",
            ", ".join(modified),
        )
    return modified


def _migrate_config_data_model_v3() -> list[str]:
    """
    Rename file_paths_battery_simulation → scenario_explorer_conf and strip
    path_consumption / path_production on disk config (+ example/minimal).
    """
    from runtime_store.data_model import (
        CURRENT_DATA_MODEL,
        is_config_document,
        migrate_config_document_to_v3,
    )
    from settings.json_io import read_json_dict, write_json_dict

    candidates = [
        resolve_config_json_path(),
        config_path("config.example.json"),
        config_path("config.minimal.json"),
    ]
    modified: list[str] = []
    for path in candidates:
        if not os.path.isfile(path):
            continue
        doc = read_json_dict(path)
        if not isinstance(doc, dict) or not is_config_document(doc):
            continue
        changed = migrate_config_document_to_v3(doc)
        if _read_data_model_version(doc) < CURRENT_DATA_MODEL:
            doc["earnie_data_model"] = CURRENT_DATA_MODEL
            changed = True
        if changed:
            write_json_dict(path, doc)
            modified.append(path)
    if modified:
        logger.info(
            "bootstrap: config data-model v3 migration (rename/strip) → %s",
            ", ".join(modified),
        )
    return modified


def _pack_json_stamp_candidates() -> list[str]:
    """Live pack JSONs plus local example/minimal sidecars that carry earnie_data_model."""
    paths = [
        resolve_config_json_path(),
        resolve_backtesting_scenarios_json_path(),
        resolve_components_json_path(),
        resolve_deviation_rules_json_path(),
        resolve_house_profiles_json_path(),
        resolve_tariffs_json_path(),
    ]
    for basename in (
        "config.example.json",
        "config.minimal.json",
        "backtesting_scenarios.example.json",
        "backtesting_scenarios.minimal.json",
        "components.example.json",
        "components.minimal.json",
        "deviation_rules.example.json",
        "house_profiles.example.json",
        "house_profiles.minimal.json",
        "tariffs.example.json",
        "tariffs.minimal.json",
    ):
        paths.append(config_path(basename))
    return paths


def _stamp_pack_jsons_to_current_data_model() -> list[str]:
    """
    Persist CURRENT_DATA_MODEL on pack/sidecar JSONs still tagged older (or missing).

    Complements the OeMAG structural migration: other files need only a version stamp
    so schemas with const=CURRENT stay valid.
    """
    from runtime_store.data_model import CURRENT_DATA_MODEL
    from settings.json_io import read_json_dict, write_json_dict

    modified: list[str] = []
    for path in _pack_json_stamp_candidates():
        if not os.path.isfile(path):
            continue
        doc = read_json_dict(path)
        if not isinstance(doc, dict):
            continue
        if _read_data_model_version(doc) >= CURRENT_DATA_MODEL:
            continue
        # write_json_dict stamps CURRENT_DATA_MODEL
        write_json_dict(path, doc)
        modified.append(path)
    if modified:
        logger.info(
            "bootstrap: stamped earnie_data_model=%s on %s",
            CURRENT_DATA_MODEL,
            ", ".join(modified),
        )
    return modified


def _bootstrap_tariffs_example() -> bool:
    dest = config_path("tariffs.example.json")
    return _copy_template_if_missing(
        dest,
        resolve_tariffs_template_path(),
        "Image-Vorlage",
    )


def _bootstrap_tariffs_schema() -> bool:
    dest = config_path("tariffs.schema.json")
    return _copy_schema_if_missing_or_stale(
        dest,
        bundled_tariffs_schema_file(),
        "share/config/tariffs.schema.json",
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
    return _copy_schema_if_missing_or_stale(
        dest,
        bundled_house_profiles_schema_file(),
        "share/config/house_profiles.schema.json",
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
    return _copy_schema_if_missing_or_stale(
        dest,
        bundled_components_schema_file(),
        "share/config/components.schema.json",
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
    return _copy_schema_if_missing_or_stale(
        dest,
        bundled_deviation_rules_schema_file(),
        "share/config/deviation_rules.schema.json",
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
    for path in _migrate_oemag_data_model_v2():
        created.append(path)
    for path in _migrate_config_data_model_v3():
        created.append(path)
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
    for path in _stamp_pack_jsons_to_current_data_model():
        created.append(path)
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

    from runtime_store.cloud_demo import is_cloud_demo
    from runtime_store.offline_demo_seed import seed_offline_live_scenario

    if is_cloud_demo():
        logger.debug("bootstrap: cloud demo — skip offline live-scenario seed.")
        return
    if seed_offline_live_scenario():
        logger.info("bootstrap: offline demo live-scenario refs seeded.")
