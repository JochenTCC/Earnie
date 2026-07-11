"""Persistenz-Hilfen für Hauskonfigurator und Szenarieneditor."""
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
from house_config.tariffs_store import load_tariffs_document
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_config_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
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


def tariffs_json_path() -> str:
    return resolve_tariffs_json_path()


def load_tariffs() -> dict:
    return load_tariffs_document(tariffs_json_path())


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
    path = resolve_house_profiles_json_path()
    if os.path.isfile(path):
        raw = read_json_document(path)
        profiles = list(raw.get("profiles", []))
    else:
        profiles = []
    profiles = [p for p in profiles if p.get("id") != profile["id"]]
    profiles.append(profile)
    save_house_profiles_document(path, {"profiles": profiles})


def save_profile_consumption_csv(profile_id: str, content: bytes, filename: str) -> str:
    """Speichert hochgeladene Verbrauchs-CSV unter config/uploads/."""
    uploads_dir = Path("config") / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "consumption.csv"
    if not safe_name.lower().endswith(".csv"):
        safe_name = f"{safe_name}.csv"
    target = uploads_dir / f"{profile_id}_{safe_name}"
    target.write_bytes(content)
    return target.as_posix()


def _load_config_document() -> dict:
    return read_json_dict(resolve_config_json_path())


def _save_config_document(data: dict) -> None:
    write_json_dict(resolve_config_json_path(), data)
    config.reinit_config()


def upsert_pv_system(raw_spec: dict, *, stable_id: str = "") -> None:
    from house_config.entity_resolution import normalize_pv_system

    data = _load_config_document()
    systems = list(data.get("pv_systems") or [])
    taken = {str(item.get("id", "")) for item in systems if item.get("id")}
    if stable_id:
        taken.discard(stable_id)
    label = str(raw_spec.get("label", "")).strip()
    entity_id = stable_id.strip() or slug_id(label or "pv_anlage", existing=taken)
    spec = {
        "id": entity_id,
        "label": label or entity_id,
        "kwp": float(raw_spec["kwp"]),
        "pv_tilt": float(raw_spec.get("pv_tilt", 25.0)),
        "pv_azimuth": float(raw_spec.get("pv_azimuth", 0.0)),
    }
    normalize_pv_system(spec, 0)
    systems = [item for item in systems if item.get("id") != entity_id]
    systems.append(spec)
    data["pv_systems"] = systems
    _save_config_document(data)


def upsert_battery(raw_spec: dict, *, stable_id: str = "") -> None:
    from house_config.entity_resolution import normalize_battery

    data = _load_config_document()
    batteries = list(data.get("batteries") or [])
    taken = {str(item.get("id", "")) for item in batteries if item.get("id")}
    if stable_id:
        taken.discard(stable_id)
    label = str(raw_spec.get("label", "")).strip()
    entity_id = stable_id.strip() or slug_id(label or "batterie", existing=taken)
    spec = {
        "id": entity_id,
        "label": label or entity_id,
        "battery_capacity_kwh": float(raw_spec["battery_capacity_kwh"]),
        "battery_max_power_kw": float(raw_spec["battery_max_power_kw"]),
        "battery_efficiency": float(raw_spec["battery_efficiency"]),
        "battery_min_soc": float(raw_spec["battery_min_soc"]),
        "battery_max_soc": float(raw_spec["battery_max_soc"]),
        "threshold_power": float(raw_spec.get("threshold_power", 0.05)),
    }
    existing_wear = None
    if stable_id:
        for item in batteries:
            if str(item.get("id", "")).strip() == entity_id:
                existing_wear = item.get("battery_wear")
                break
    if raw_spec.get("battery_wear") is not None:
        spec["battery_wear"] = raw_spec["battery_wear"]
    elif existing_wear is not None:
        spec["battery_wear"] = existing_wear
    elif data.get("battery_wear") is not None:
        spec["battery_wear"] = dict(data["battery_wear"])
    else:
        spec["battery_wear"] = {"enabled": False}
    normalize_battery(spec, 0)
    batteries = [item for item in batteries if item.get("id") != entity_id]
    batteries.append(spec)
    data["batteries"] = batteries
    _save_config_document(data)


def get_planning_tariff_selection() -> tuple[str, str]:
    runtime = _load_config_document().get("runtime_settings", {})
    if not isinstance(runtime, dict):
        return "", ""
    return (
        str(runtime.get("import_tariff_id", "") or "").strip(),
        str(runtime.get("export_tariff_id", "") or "").strip(),
    )


def save_planning_tariff_selection(import_tariff_id: str, export_tariff_id: str) -> None:
    data = _load_config_document()
    runtime = data.setdefault("runtime_settings", {})
    if not isinstance(runtime, dict):
        raise ValueError("runtime_settings muss ein Objekt sein.")
    runtime["import_tariff_id"] = import_tariff_id.strip()
    runtime["export_tariff_id"] = export_tariff_id.strip()
    _save_config_document(data)


def get_runtime_scenario_refs() -> dict:
    """Entitäts-Referenzen des Runtime-Szenarios aus runtime_settings."""
    runtime = _load_config_document().get("runtime_settings", {})
    if not isinstance(runtime, dict):
        return {}
    return {
        "battery_id": str(runtime.get("battery_id", "") or "").strip(),
        "pv_system_id": str(runtime.get("pv_system_id", "") or "").strip(),
        "import_tariff_id": str(runtime.get("import_tariff_id", "") or "").strip(),
        "export_tariff_id": str(runtime.get("export_tariff_id", "") or "").strip(),
        "house_profile_id": str(runtime.get("house_profile_id", "") or "").strip(),
    }


def save_runtime_scenario_refs(
    *,
    battery_id: str,
    pv_system_id: str,
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
) -> None:
    """Speichert Entitäts-Referenzen für das Runtime-Szenario (Baseline)."""
    data = _load_config_document()
    runtime = data.setdefault("runtime_settings", {})
    if not isinstance(runtime, dict):
        raise ValueError("runtime_settings muss ein Objekt sein.")
    runtime["battery_id"] = battery_id.strip()
    runtime["pv_system_id"] = pv_system_id.strip()
    runtime["import_tariff_id"] = import_tariff_id.strip()
    runtime["export_tariff_id"] = export_tariff_id.strip()
    runtime["house_profile_id"] = house_profile_id.strip()
    for legacy_geo in ("latitude", "longitude", "timezone_name"):
        runtime.pop(legacy_geo, None)
    _save_config_document(data)


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
