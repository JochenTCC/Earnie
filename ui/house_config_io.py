"""Persistenz-Hilfen für Hauskonfigurator und Szenarieneditor."""
from __future__ import annotations

import json
import os
from pathlib import Path

import config
from house_config.profiles_store import (
    load_house_profiles_document,
    save_house_profiles_document,
)
from house_config.tariffs_store import load_tariffs_document
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
)


def read_json_document(path: str) -> dict:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return json.loads(Path(path).read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Datei '{path}' ist weder UTF-8 noch cp1252 lesbar.")


def write_json_document(path: str, data: dict) -> None:
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


def save_house_profiles(doc: dict) -> None:
    save_house_profiles_document(resolve_house_profiles_json_path(), doc)


def load_tariffs() -> dict:
    return load_tariffs_document(resolve_tariffs_json_path())


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


def upsert_house_profile(profile: dict) -> None:
    path = resolve_house_profiles_json_path()
    if os.path.isfile(path):
        raw = read_json_document(path)
        profiles = list(raw.get("profiles", []))
    else:
        profiles = []
    profiles = [p for p in profiles if p.get("id") != profile["id"]]
    profiles.append(profile)
    save_house_profiles_document(path, {"profiles": profiles})


def upsert_scenario(scenario: dict) -> None:
    doc = load_backtesting_scenarios_raw()
    scenarios = doc.get("scenarios", [])
    updated = [s for s in scenarios if s.get("id") != scenario["id"]]
    updated.append(scenario)
    doc["scenarios"] = updated
    save_backtesting_scenarios(doc)


def preview_baseload(annual_kwh: float, consumers: list[dict]) -> dict:
    return compute_baseload_kwh(annual_kwh, consumers)


def compute_baseload_kwh(annual_kwh: float, consumers: list[dict]) -> dict:
    from house_config.baseload import compute_baseload_kwh as _compute

    return _compute(annual_kwh, consumers)
