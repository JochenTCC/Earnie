"""Persistenz-Hilfen für Hauskonfigurator und Szenarienkonfigurator."""
from __future__ import annotations

import json
import os
from pathlib import Path

import config
from house_config.id_slug import slug_id
from house_config.profiles_store import (
    load_house_profiles_document,
    save_house_profiles_document,
)
from house_config.tariffs_store import append_monthly_rate, load_tariffs_document
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
    resolve_uploads_dir,
)
from settings.json_io import read_json_dict, write_json_dict

def read_json_document(path: str) -> dict:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return json.loads(Path(path).read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Datei '{path}' ist weder UTF-8 noch cp1252 lesbar.")

def write_json_document(path: str, data: dict) -> None:
    from runtime_store.data_model import stamp_data_model

    stamp_data_model(data)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, target)

def load_house_profiles() -> dict:
    return load_house_profiles_document(resolve_house_profiles_json_path())

def house_doc_for_save(doc: dict) -> dict:
    """Normalize in-memory house doc (profiles dict|list) for ``save_house_profiles_document``."""
    profiles = doc.get("profiles")
    if isinstance(profiles, dict):
        profile_list = list(profiles.values())
    elif isinstance(profiles, list):
        profile_list = list(profiles)
    else:
        profile_list = []
    out: dict = {"profiles": profile_list}
    plant = doc.get("plant")
    if isinstance(plant, dict) and plant:
        out["plant"] = dict(plant)
    if "earnie_data_model" in doc:
        out["earnie_data_model"] = doc["earnie_data_model"]
    return out

def save_house_profiles(doc: dict) -> None:
    save_house_profiles_document(
        resolve_house_profiles_json_path(), house_doc_for_save(doc)
    )

def tariffs_json_path() -> str:
    return resolve_tariffs_json_path()

def load_tariffs() -> dict:
    return load_tariffs_document(tariffs_json_path())

def append_tariff_monthly_rate(
    *,
    side: str,
    tariff_id: str,
    year: int,
    month: int,
    tariff_cent_kwh: float,
) -> None:
    """Persist one monthly_rates row and reload live config."""
    append_monthly_rate(
        tariffs_json_path(),
        side=side,
        tariff_id=tariff_id,
        year=year,
        month=month,
        tariff_cent_kwh=tariff_cent_kwh,
    )
    config.reload_config()

def load_backtesting_scenarios_raw() -> dict:
    path = resolve_backtesting_scenarios_json_path()
    if not os.path.isfile(path):
        return {"scenarios": []}
    return read_json_document(path)

def save_backtesting_scenarios(doc: dict) -> None:
    write_json_document(resolve_backtesting_scenarios_json_path(), doc)
    config.reinit_config()

def list_batteries() -> list[dict]:
    return config.get_batteries()

def list_pv_systems() -> list[dict]:
    return config.get_pv_systems()

def list_import_tariffs() -> list[dict]:
    doc = load_tariffs()
    return list(doc.get("import_tariffs", {}).values())

def list_export_tariffs() -> list[dict]:
    doc = load_tariffs()
    return list(doc.get("export_tariffs", {}).values())

def load_tariffs_catalog_meta() -> dict:
    doc = load_tariffs()
    meta: dict = {}
    if doc.get("catalog_as_of"):
        meta["catalog_as_of"] = doc["catalog_as_of"]
    return meta

def upsert_house_profile(profile: dict) -> None:
    from house_config.label_uniqueness import assert_unique_label, assert_unique_labels_in_list

    path = resolve_house_profiles_json_path()
    raw: dict = {}
    if os.path.isfile(path):
        raw = read_json_document(path)
        profiles = list(raw.get("profiles", []))
    else:
        profiles = []
    profile_id = str(profile.get("id", "")).strip()
    assert_unique_label(profile.get("label"), profiles, exclude_id=profile_id)
    consumers = list(profile.get("consumers") or [])
    assert_unique_labels_in_list(consumers)
    profiles = [p for p in profiles if p.get("id") != profile["id"]]
    profiles.append(profile)
    payload: dict = {"profiles": profiles}
    plant = raw.get("plant")
    if isinstance(plant, dict) and plant:
        payload["plant"] = dict(plant)
    if "earnie_data_model" in raw:
        payload["earnie_data_model"] = raw["earnie_data_model"]
    save_house_profiles_document(path, payload)


from ui.house_config_csv_io import (  # noqa: E402
    _resampled_upload_csv_name,
    _stable_upload_csv_name,
    apply_csv_path_pending,
    csv_upload_widget_key,
    queue_csv_path_update,
    save_balance_total_from_component_paths,
    save_energiemonitor_balance_profile_csvs,
    save_energiemonitor_profile_csvs,
    save_profile_consumption_csv,
    single_csv_upload,
)
from ui.house_config_entities_io import (  # noqa: E402
    _live_scenario_settings,
    _load_components_document,
    _load_config_document,
    _save_components_document,
    _save_config_document,
    compute_baseload_kwh,
    delete_battery,
    delete_pv_system,
    delete_scenario,
    get_live_scenario_refs,
    get_planning_tariff_selection,
    get_runtime_scenario_refs,
    load_main_config,
    preview_baseload,
    reorder_scenarios,
    save_live_scenario_id,
    save_live_scenario_refs,
    save_main_config,
    save_planning_tariff_selection,
    save_runtime_scenario_refs,
    upsert_battery,
    upsert_pv_system,
    upsert_scenario,
)

__all__ = [
    "_live_scenario_settings",
    "_load_components_document",
    "_load_config_document",
    "_resampled_upload_csv_name",
    "_save_components_document",
    "_save_config_document",
    "_stable_upload_csv_name",
    "append_tariff_monthly_rate",
    "apply_csv_path_pending",
    "compute_baseload_kwh",
    "csv_upload_widget_key",
    "delete_battery",
    "delete_pv_system",
    "delete_scenario",
    "get_live_scenario_refs",
    "get_planning_tariff_selection",
    "get_runtime_scenario_refs",
    "house_doc_for_save",
    "list_batteries",
    "list_export_tariffs",
    "list_import_tariffs",
    "list_pv_systems",
    "load_backtesting_scenarios_raw",
    "load_house_profiles",
    "load_main_config",
    "load_tariffs",
    "load_tariffs_catalog_meta",
    "preview_baseload",
    "queue_csv_path_update",
    "read_json_document",
    "reorder_scenarios",
    "save_backtesting_scenarios",
    "save_balance_total_from_component_paths",
    "save_energiemonitor_balance_profile_csvs",
    "save_energiemonitor_profile_csvs",
    "save_house_profiles",
    "save_live_scenario_id",
    "save_live_scenario_refs",
    "save_main_config",
    "save_planning_tariff_selection",
    "save_profile_consumption_csv",
    "save_runtime_scenario_refs",
    "single_csv_upload",
    "tariffs_json_path",
    "upsert_battery",
    "upsert_house_profile",
    "upsert_pv_system",
    "upsert_scenario",
    "write_json_document",
]
