"""Hausprofile für Backtesting-Planung (Verbraucher, Jahresverbrauch, Grundlast)."""
from __future__ import annotations

import json
import os

from house_config.baseload import compute_baseload_kwh
from house_config.consumption_csv import load_hourly_profile_csv

SCHEDULE_FLEX = frozenset({"fixed", "day", "any"})
CONSUMER_TYPES = frozenset({"generic", "thermal_annual"})


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {"profiles": []}
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                return json.load(handle)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"house_profiles.json '{path}' ist weder UTF-8 noch cp1252 lesbar.")


def _normalize_schedule(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    runs = int(raw.get("runs_per_week", 0) or 0)
    duration = float(raw.get("duration_h", 0.0) or 0.0)
    flex = str(raw.get("start_flexibility", "day")).strip().lower()
    if flex not in SCHEDULE_FLEX:
        raise ValueError(
            f"schedule.start_flexibility muss einer von {sorted(SCHEDULE_FLEX)} sein."
        )
    return {
        "runs_per_week": max(0, runs),
        "duration_h": max(0.0, duration),
        "start_flexibility": flex,
    }


def _normalize_consumer(raw: dict, index: int, profile_id: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"profiles '{profile_id}' consumers[{index}] muss ein Objekt sein.")
    consumer_id = str(raw.get("id", "")).strip()
    if not consumer_id:
        raise ValueError(f"profiles '{profile_id}' consumers[{index}]: id fehlt.")
    consumer_type = str(raw.get("type", "generic")).strip().lower()
    if consumer_type not in CONSUMER_TYPES:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}]: "
            f"type muss generic oder thermal_annual sein."
        )
    label = str(raw.get("label", consumer_id)).strip() or consumer_id
    spec: dict = {
        "id": consumer_id,
        "label": label,
        "type": consumer_type,
        "nominal_power_kw": float(raw.get("nominal_power_kw", 0.0) or 0.0),
        "annual_kwh": float(raw.get("annual_kwh", 0.0) or 0.0),
        "profile_csv": str(raw.get("profile_csv", "")).strip(),
        "schedule": _normalize_schedule(raw.get("schedule")),
    }
    if consumer_type == "thermal_annual":
        spec["thermal"] = {
            "living_area_m2": float(raw.get("living_area_m2", 0.0) or 0.0),
            "building_class": int(raw.get("building_class", 3)),
            "heat_pump_type": str(raw.get("heat_pump_type", "luft")).strip().lower(),
            "persons": int(raw.get("persons", 2)),
            "target_temp_c": float(raw.get("target_temp_c", 21.5)),
            "heating_limit_c": float(raw.get("heating_limit_c", 15.0)),
        }
    return spec


def _normalize_profile(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"profiles[{index}] muss ein Objekt sein.")
    profile_id = str(raw.get("id", "")).strip()
    if not profile_id:
        raise ValueError(f"profiles[{index}]: id fehlt.")
    label = str(raw.get("label", profile_id)).strip() or profile_id
    annual_kwh = float(raw.get("annual_kwh", 0.0) or 0.0)
    latitude = float(raw.get("latitude", 48.0) or 48.0)
    longitude = float(raw.get("longitude", 10.0) or 10.0)
    total_profile_csv = str(raw.get("total_profile_csv", "")).strip()
    consumers_raw = raw.get("consumers", [])
    if not isinstance(consumers_raw, list):
        raise ValueError(f"profiles '{profile_id}': consumers muss ein Array sein.")
    consumers: list[dict] = []
    seen: set[str] = set()
    for c_index, item in enumerate(consumers_raw):
        consumer = _normalize_consumer(item, c_index, profile_id)
        if consumer["type"] == "thermal_annual" and consumer.get("thermal"):
            consumer["thermal"]["latitude"] = latitude
            consumer["thermal"]["longitude"] = longitude
        if consumer["id"] in seen:
            raise ValueError(
                f"profiles '{profile_id}': doppelte consumer id '{consumer['id']}'."
            )
        seen.add(consumer["id"])
        consumers.append(consumer)
    baseload = compute_baseload_kwh(annual_kwh, consumers)
    return {
        "id": profile_id,
        "label": label,
        "annual_kwh": annual_kwh,
        "total_profile_csv": total_profile_csv,
        "consumers": consumers,
        "baseload_kwh": baseload["baseload_kwh"],
        "consumer_kwh": baseload["consumer_kwh"],
        "baseload_min_kwh": baseload["baseload_min_kwh"],
    }


def normalize_house_profiles_document(doc: dict) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("house_profiles.json muss ein Objekt sein.")
    raw_profiles = doc.get("profiles", [])
    if not isinstance(raw_profiles, list):
        raise ValueError("profiles muss ein Array sein.")
    profiles: dict[str, dict] = {}
    for index, item in enumerate(raw_profiles):
        spec = _normalize_profile(item, index)
        if spec["id"] in profiles:
            raise ValueError(f"profiles: doppelte id '{spec['id']}'.")
        profiles[spec["id"]] = spec
    return {"profiles": profiles}


def load_house_profiles_document(path: str) -> dict:
    return normalize_house_profiles_document(_read_json(path))


def save_house_profiles_document(path: str, doc: dict) -> None:
    normalized = normalize_house_profiles_document(doc)
    serializable = {
        "profiles": [
            {
                "id": p["id"],
                "label": p["label"],
                "annual_kwh": p["annual_kwh"],
                "total_profile_csv": p.get("total_profile_csv", ""),
                "consumers": [_serialize_consumer(c) for c in p["consumers"]],
            }
            for p in normalized["profiles"].values()
        ]
    }
    target = os.path.abspath(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(serializable, handle, indent=4, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, target)


def _serialize_consumer(consumer: dict) -> dict:
    out: dict = {
        "id": consumer["id"],
        "label": consumer["label"],
        "type": consumer["type"],
        "nominal_power_kw": consumer["nominal_power_kw"],
        "annual_kwh": consumer["annual_kwh"],
    }
    if consumer.get("profile_csv"):
        out["profile_csv"] = consumer["profile_csv"]
    if consumer.get("schedule"):
        out["schedule"] = consumer["schedule"]
    if consumer["type"] == "thermal_annual" and consumer.get("thermal"):
        out.update(consumer["thermal"])
    return out


def profile_list(doc: dict) -> list[dict]:
    return list(doc.get("profiles", {}).values())


def load_profile_total_series(profile: dict) -> list[tuple[str, float]] | None:
    """Lädt Gesamtverbrauchs-CSV falls gesetzt."""
    csv_path = profile.get("total_profile_csv", "")
    if not csv_path:
        return None
    return load_hourly_profile_csv(csv_path)
