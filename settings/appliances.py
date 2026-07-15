"""Normalisierung und Persistenz manueller Geräte (appliances)."""
from __future__ import annotations

import logging

from house_config.earnie_role import is_earnie_manual, manual_recommendation_horizon_h
from settings.json_io import read_json_dict, write_json_dict

logger = logging.getLogger(__name__)

_LEGACY_APPLIANCES_WARNED = False


def optional_positive(value, appliance_id: str, field: str, *, allow_zero: bool):
    if value is None:
        return None
    number = float(value)
    if number < 0 or (not allow_zero and number == 0):
        bound = ">= 0" if allow_zero else "> 0"
        raise ValueError(
            f"Kritischer Konfigurationsfehler: appliances '{appliance_id}': "
            f"{field} muss {bound} sein."
        )
    return number


def normalize_appliance(raw: dict, index: int) -> dict:
    """Manuelles Gerät (Empfehlungsmodus): Anzeigename + Leistungsquelle."""
    if not isinstance(raw, dict):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: appliances[{index}] muss ein Objekt sein."
        )
    appliance_id = str(raw.get("id", "")).strip()
    if not appliance_id:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: appliances[{index}]: id fehlt."
        )
    power_source = str(raw.get("power_source", "")).strip().lower()
    if power_source not in ("loxone", "manual"):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: appliances '{appliance_id}': "
            "power_source muss 'loxone' oder 'manual' sein."
        )
    loxone_power_name = str(raw.get("loxone_power_name", "")).strip()
    if power_source == "loxone" and not loxone_power_name:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: appliances '{appliance_id}': "
            "power_source=loxone erfordert loxone_power_name."
        )
    default_power_kw = optional_positive(
        raw.get("default_power_kw"), appliance_id, "default_power_kw", allow_zero=True
    )
    if power_source == "loxone" and not default_power_kw:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: appliances '{appliance_id}': "
            "power_source=loxone erfordert default_power_kw > 0 (Nennleistung für die "
            "Kostenbewertung; wird später vom Adaptionsalgo gepflegt)."
        )
    return {
        "id": appliance_id,
        "name": str(raw.get("name", appliance_id)),
        "power_source": power_source,
        "loxone_power_name": loxone_power_name,
        "default_power_kw": default_power_kw,
        "default_runtime_h": optional_positive(
            raw.get("default_runtime_h"), appliance_id, "default_runtime_h", allow_zero=False
        ),
    }


def normalize_appliance_list(raw: list) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError(
            "Kritischer Konfigurationsfehler: 'appliances' muss ein Array sein."
        )
    seen: set[str] = set()
    appliances: list[dict] = []
    for index, item in enumerate(raw):
        spec = normalize_appliance(item, index)
        if spec["id"] in seen:
            raise ValueError(
                "Kritischer Konfigurationsfehler: appliances enthält doppelte "
                f"id '{spec['id']}'."
            )
        seen.add(spec["id"])
        appliances.append(spec)
    return appliances


def warn_legacy_appliances_block() -> None:
    global _LEGACY_APPLIANCES_WARNED
    if _LEGACY_APPLIANCES_WARNED:
        return
    _LEGACY_APPLIANCES_WARNED = True
    logger.warning(
        "config.json 'appliances[]' ist veraltet — Verbraucher mit "
        "appliance_recommendation ins Hausprofil migrieren (1.96d)."
    )


def reject_legacy_appliances_block(raw_config: dict) -> None:
    """2.0 gate: root appliances[] must not be present."""
    if raw_config.get("appliances"):
        raise ValueError(
            "Block 'appliances' in config.json ist entfernt (2.0). "
            "Empfehlungsgeräte als type:generic mit appliance_recommendation "
            "im Hausprofil konfigurieren."
        )


def normalize_appliance_recommendation_block(
    raw: dict | None,
    *,
    consumer_id: str,
    nominal_power_kw: float,
    loxone_power_name: str = "",
) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: consumers '{consumer_id}': "
            "appliance_recommendation muss ein Objekt sein."
        )
    power_source = str(raw.get("power_source", "manual")).strip().lower()
    if power_source not in ("loxone", "manual"):
        raise ValueError(
            f"Kritischer Konfigurationsfehler: consumers '{consumer_id}': "
            "appliance_recommendation.power_source muss 'loxone' oder 'manual' sein."
        )
    marker = str(loxone_power_name or raw.get("loxone_power_name", "")).strip()
    if power_source == "loxone" and not marker:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: consumers '{consumer_id}': "
            "power_source=loxone erfordert loxone_inputs.power_name."
        )
    default_runtime_h = optional_positive(
        raw.get("default_runtime_h"),
        consumer_id,
        "appliance_recommendation.default_runtime_h",
        allow_zero=False,
    )
    default_power_kw = optional_positive(
        raw.get("default_power_kw", nominal_power_kw),
        consumer_id,
        "appliance_recommendation.default_power_kw",
        allow_zero=True,
    )
    if power_source == "loxone" and not default_power_kw:
        raise ValueError(
            f"Kritischer Konfigurationsfehler: consumers '{consumer_id}': "
            "appliance_recommendation erfordert default_power_kw > 0 bei power_source=loxone."
        )
    return {
        "power_source": power_source,
        "default_power_kw": default_power_kw,
        "default_runtime_h": default_runtime_h or 2.0,
    }


def _loxone_power_name_from_consumer(consumer: dict) -> str:
    inputs = consumer.get("loxone_inputs")
    if isinstance(inputs, dict):
        name = str(inputs.get("power_name", "")).strip()
        if name:
            return name
    rec = consumer.get("appliance_recommendation")
    if isinstance(rec, dict):
        return str(rec.get("loxone_power_name", "")).strip()
    return ""


def appliance_from_profile_consumer(consumer: dict) -> dict:
    rec = consumer.get("appliance_recommendation")
    if not isinstance(rec, dict):
        raise ValueError(
            f"Hausprofil-Verbraucher '{consumer.get('id')}': appliance_recommendation fehlt."
        )
    consumer_id = str(consumer["id"])
    loxone_power_name = _loxone_power_name_from_consumer(consumer)
    normalized = normalize_appliance_recommendation_block(
        rec,
        consumer_id=consumer_id,
        nominal_power_kw=float(consumer.get("nominal_power_kw", 0.0) or 0.0),
        loxone_power_name=loxone_power_name,
    )
    if normalized is None:
        raise ValueError(
            f"Hausprofil-Verbraucher '{consumer_id}': appliance_recommendation fehlt."
        )
    legacy_id = str(consumer.get("legacy_id", "")).strip()
    spec = {
        "id": consumer_id,
        "name": str(consumer.get("label", consumer_id)),
        "power_source": normalized["power_source"],
        "default_power_kw": normalized["default_power_kw"],
        "default_runtime_h": normalized["default_runtime_h"],
    }
    if loxone_power_name:
        spec["loxone_inputs"] = {"power_name": loxone_power_name}
    if legacy_id and legacy_id != consumer_id:
        spec["legacy_id"] = legacy_id
    spec["recommendation_horizon_h"] = manual_recommendation_horizon_h(consumer)
    return spec


def recommendation_appliances_from_profile(house_profile: dict) -> list[dict]:
    consumers = house_profile.get("consumers") or []
    appliances: list[dict] = []
    for raw in consumers:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("type", "")).strip().lower() != "generic":
            continue
        if not is_earnie_manual(raw):
            continue
        appliances.append(appliance_from_profile_consumer(raw))
    return appliances


def update_appliance_defaults_in_house_profile(
    house_profiles_path: str,
    profile_id: str,
    appliance_id: str,
    *,
    power_kw: float,
    runtime_h: float,
) -> dict:
    if power_kw < 0:
        raise ValueError(
            f"update_appliance_defaults: power_kw muss >= 0 sein (erhalten: {power_kw})."
        )
    if runtime_h <= 0:
        raise ValueError(
            f"update_appliance_defaults: runtime_h muss > 0 sein (erhalten: {runtime_h})."
        )
    data = read_json_dict(house_profiles_path)
    profiles = data.get("profiles", [])
    if isinstance(profiles, dict):
        profile = profiles.get(profile_id)
    else:
        profile = next((item for item in profiles if item.get("id") == profile_id), None)
    if profile is None:
        raise KeyError(
            f"update_appliance_defaults: unbekannte house_profile_id '{profile_id}'."
        )
    consumers = profile.get("consumers") or []
    target_index = None
    for index, item in enumerate(consumers):
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "")).strip() == appliance_id:
            target_index = index
            break
    if target_index is None:
        raise KeyError(
            f"update_appliance_defaults: unbekannte appliance_id '{appliance_id}'."
        )
    entry = dict(consumers[target_index])
    entry["nominal_power_kw"] = float(power_kw)
    rec = dict(entry.get("appliance_recommendation") or {})
    rec["default_power_kw"] = float(power_kw)
    rec["default_runtime_h"] = float(runtime_h)
    loxone_power_name = _loxone_power_name_from_consumer(entry)
    normalize_appliance_recommendation_block(
        rec,
        consumer_id=appliance_id,
        nominal_power_kw=float(power_kw),
        loxone_power_name=loxone_power_name,
    )
    entry["appliance_recommendation"] = rec
    consumers[target_index] = entry
    profile["consumers"] = consumers
    write_json_dict(house_profiles_path, data)
    return data


def normalize_appliance_recommendation(raw: dict | None) -> dict:
    from optimizer.appliance_recommendation import (
        DEFAULT_ABS_MARGIN_CENT,
        DEFAULT_PCT_STARS_1,
        DEFAULT_PCT_STARS_4,
    )

    defaults = {
        "abs_margin_cent": DEFAULT_ABS_MARGIN_CENT,
        "pct_stars_4": DEFAULT_PCT_STARS_4,
        "pct_stars_1": DEFAULT_PCT_STARS_1,
    }
    if raw is None:
        return dict(defaults)
    if not isinstance(raw, dict):
        raise ValueError(
            "Kritischer Konfigurationsfehler: 'appliance_recommendation' muss ein Objekt sein."
        )
    result = dict(defaults)
    for key in defaults:
        if key in raw and raw[key] is not None:
            result[key] = float(raw[key])
    margin = result["abs_margin_cent"]
    pct_4 = result["pct_stars_4"]
    pct_1 = result["pct_stars_1"]
    if margin < 0:
        raise ValueError("appliance_recommendation.abs_margin_cent muss >= 0 sein.")
    if pct_4 <= 0:
        raise ValueError("appliance_recommendation.pct_stars_4 muss > 0 sein.")
    if pct_1 <= pct_4:
        raise ValueError("appliance_recommendation.pct_stars_1 muss > pct_stars_4 sein.")
    return result


def update_appliance_defaults_in_file(
    config_path: str,
    appliance_id: str,
    *,
    power_kw: float,
    runtime_h: float,
) -> dict:
    """Persistiert Nennleistung und Laufzeit-Vorbelegung; gibt aktualisiertes config-Dict zurück."""
    if power_kw < 0:
        raise ValueError(
            f"update_appliance_defaults: power_kw muss >= 0 sein (erhalten: {power_kw})."
        )
    if runtime_h <= 0:
        raise ValueError(
            f"update_appliance_defaults: runtime_h muss > 0 sein (erhalten: {runtime_h})."
        )
    data = read_json_dict(config_path)
    raw = data.get("appliances")
    if not isinstance(raw, list):
        raise ValueError(
            "Kritischer Konfigurationsfehler: 'appliances' muss ein Array sein."
        )
    target_index = None
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "")).strip() == appliance_id:
            target_index = index
            break
    if target_index is None:
        raise KeyError(
            f"update_appliance_defaults: unbekannte appliance_id '{appliance_id}'."
        )
    entry = dict(raw[target_index])
    entry["default_power_kw"] = float(power_kw)
    entry["default_runtime_h"] = float(runtime_h)
    normalize_appliance(entry, target_index)
    raw[target_index] = entry
    data["appliances"] = raw
    write_json_dict(config_path, data)
    return data


def update_appliance_recommendation_in_file(
    config_path: str,
    current_settings: dict,
    new_settings: dict,
) -> dict:
    data = read_json_dict(config_path)
    merged = normalize_appliance_recommendation({**current_settings, **new_settings})
    data["appliance_recommendation"] = merged
    write_json_dict(config_path, data)
    return data
