"""Hausprofile für Backtesting-Planung (Verbraucher, Jahresverbrauch, Grundlast)."""
from __future__ import annotations

import json
import os

from house_config.baseload import compute_baseload_kwh
from house_config.earnie_role import (
    DEFAULT_MANUAL_HORIZON_H,
    EARNIE_ROLE_FLEX,
    EARNIE_ROLE_KNOWN,
    EARNIE_ROLE_MANUAL,
    EARNIE_ROLES,
    infer_earnie_role_from_legacy,
)
from house_config.consumption_csv import load_hourly_profile_csv
from house_config.ev_profile import normalize_ev_charging_schedule
from house_config.geo_timezone import lookup_timezone_name
from house_config.generic_schedule import (
    derive_duration_h,
    generic_annual_kwh,
    normalize_generic_schedule,
)

CONSUMER_TYPES = frozenset({"generic", "thermal_annual", "ev", "thermal_rc"})


def _copy_loxone_binding(raw: dict, spec: dict) -> None:
    loxone_inputs = raw.get("loxone_inputs")
    if isinstance(loxone_inputs, dict) and loxone_inputs:
        spec["loxone_inputs"] = dict(loxone_inputs)
    loxone_outputs = raw.get("loxone_outputs")
    if isinstance(loxone_outputs, dict) and loxone_outputs:
        spec["loxone_outputs"] = dict(loxone_outputs)


def _legacy_loxone_power_name(raw: dict) -> str:
    rec = raw.get("appliance_recommendation")
    if isinstance(rec, dict):
        return str(rec.get("loxone_power_name", "")).strip()
    return ""


def _loxone_power_name_from_raw(raw: dict) -> str:
    inputs = raw.get("loxone_inputs")
    if isinstance(inputs, dict):
        name = str(inputs.get("power_name", "")).strip()
        if name:
            return name
    return _legacy_loxone_power_name(raw)


def _set_generic_loxone_inputs(spec: dict, power_name: str) -> None:
    if power_name:
        spec["loxone_inputs"] = {"power_name": power_name}
    else:
        spec.pop("loxone_inputs", None)


def _thermal_rc_source(raw: dict) -> dict:
    nested = raw.get("thermal_rc")
    if isinstance(nested, dict):
        return nested
    return raw


def _normalize_thermal_rc(raw: dict, index: int, profile_id: str) -> dict:
    source = _thermal_rc_source(raw)
    volume = float(source.get("water_volume_liters", 0.0) or 0.0)
    if volume <= 0:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}]: "
            "water_volume_liters muss > 0 sein."
        )
    efficiency = float(source.get("heating_efficiency", 0.0) or 0.0)
    if not 0.0 < efficiency <= 1.0:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}]: "
            "heating_efficiency muss zwischen 0 (exklusiv) und 1 liegen."
        )
    heat_loss = source.get("heat_loss_kw_per_k")
    if heat_loss is None:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}]: heat_loss_kw_per_k fehlt."
        )
    heat_loss = float(heat_loss)
    if heat_loss < 0:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}]: "
            "heat_loss_kw_per_k muss >= 0 sein."
        )
    setpoint = source.get("setpoint_c")
    tolerance = source.get("tolerance_c")
    if setpoint is None or tolerance is None:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}]: "
            "setpoint_c und tolerance_c sind Pflicht für thermal_rc."
        )
    block: dict = {
        "water_volume_liters": volume,
        "setpoint_c": float(setpoint),
        "tolerance_c": float(tolerance),
        "heat_loss_kw_per_k": heat_loss,
        "heating_efficiency": efficiency,
    }
    extra_paths = source.get("heat_paths")
    if isinstance(extra_paths, list) and extra_paths:
        block["heat_paths"] = extra_paths
    return block


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


def _normalize_schedule(raw: dict | None, *, consumer: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    runs = int(raw.get("runs_per_week", 0) or 0)
    if runs <= 0:
        return None
    schedule_input = dict(raw)
    if float(schedule_input.get("duration_h", 0.0) or 0.0) <= 0:
        derived = derive_duration_h({**consumer, "schedule": schedule_input})
        if derived is not None and derived > 0:
            schedule_input["duration_h"] = derived
    return normalize_generic_schedule(schedule_input)


def _normalize_earnie_role(
    spec: dict,
    raw: dict,
    *,
    consumer_id: str,
    profile_id: str,
    index: int,
) -> None:
    """Setzt earnie_role und abhängige Felder für generic-Verbraucher."""
    schedule = spec.get("schedule")
    if not schedule:
        spec.pop("earnie_role", None)
        spec.pop("appliance_recommendation", None)
        return

    explicit = str(raw.get("earnie_role", "") or "").strip().lower()
    if explicit in EARNIE_ROLES:
        role = explicit
    else:
        role = infer_earnie_role_from_legacy({**raw, "schedule": schedule})

    spec["earnie_role"] = role

    if role == EARNIE_ROLE_KNOWN:
        schedule["start_shift_h"] = 0.0
        spec.pop("appliance_recommendation", None)
        _set_generic_loxone_inputs(spec, _loxone_power_name_from_raw(raw))
        return

    if role == EARNIE_ROLE_FLEX:
        shift = float(schedule.get("start_shift_h", 0.0) or 0.0)
        if shift <= 0:
            raise ValueError(
                f"profiles '{profile_id}' consumers[{index}] '{consumer_id}': "
                "earnie_role=flex erfordert schedule.start_shift_h > 0."
            )
        spec.pop("appliance_recommendation", None)
        return

    from settings import appliances as appliance_settings

    shift = float(schedule.get("start_shift_h", 0.0) or 0.0)
    if shift < 1:
        schedule["start_shift_h"] = DEFAULT_MANUAL_HORIZON_H
    rec = raw.get("appliance_recommendation")
    if isinstance(rec, dict):
        rec_input = dict(rec)
    else:
        rec_input = {
            "power_source": "manual",
            "default_power_kw": spec["nominal_power_kw"],
            "default_runtime_h": float(schedule.get("duration_h", 2.0) or 2.0),
        }
    power_source = str(rec_input.get("power_source", "manual")).strip().lower()
    power_name = _loxone_power_name_from_raw(raw)
    if power_source == "loxone" and not power_name:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}] '{consumer_id}': "
            "earnie_role=manual mit power_source=loxone erfordert loxone_inputs.power_name."
        )
    if power_source == "loxone":
        _set_generic_loxone_inputs(spec, power_name)
    else:
        spec.pop("loxone_inputs", None)
    spec["appliance_recommendation"] = appliance_settings.normalize_appliance_recommendation_block(
        rec_input,
        consumer_id=consumer_id,
        nominal_power_kw=spec["nominal_power_kw"],
        loxone_power_name=power_name if power_source == "loxone" else "",
    )


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
            f"type muss generic, thermal_annual, ev oder thermal_rc sein."
        )
    label = str(raw.get("label", consumer_id)).strip() or consumer_id
    spec: dict = {
        "id": consumer_id,
        "label": label,
        "type": consumer_type,
        "nominal_power_kw": float(raw.get("nominal_power_kw", 0.0) or 0.0),
        "profile_csv": str(raw.get("profile_csv", "")).strip(),
    }
    if consumer_type == "generic":
        spec["schedule"] = _normalize_schedule(raw.get("schedule"), consumer=raw)
        spec["annual_kwh"] = generic_annual_kwh(spec)
        _normalize_earnie_role(
            spec,
            raw,
            consumer_id=consumer_id,
            profile_id=profile_id,
            index=index,
        )
    elif consumer_type == "ev":
        battery_capacity = float(raw.get("battery_capacity_kwh", 0.0) or 0.0)
        if battery_capacity <= 0:
            raise ValueError(
                f"profiles '{profile_id}' consumers[{index}]: "
                "battery_capacity_kwh muss > 0 sein."
            )
        spec["min_power_kw"] = float(raw.get("min_power_kw", 0.0) or 0.0)
        spec["min_on_quarterhours"] = max(0, int(raw.get("min_on_quarterhours", 0) or 0))
        spec["battery_capacity_kwh"] = battery_capacity
        spec["charging_schedule"] = normalize_ev_charging_schedule(raw.get("charging_schedule"))
        _copy_loxone_binding(raw, spec)
    if consumer_type == "thermal_annual":
        hwb_raw = raw.get("hwb_kwh_m2")
        hwb_value = float(hwb_raw) if hwb_raw not in (None, "") else 0.0
        spec["thermal"] = {
            "living_area_m2": float(raw.get("living_area_m2", 0.0) or 0.0),
            "building_class": int(raw.get("building_class", 3)),
            "heat_pump_type": str(raw.get("heat_pump_type", "luft")).strip().lower(),
            "persons": int(raw.get("persons", 2)),
            "target_temp_c": float(raw.get("target_temp_c", 21.5)),
            "heating_limit_c": float(raw.get("heating_limit_c", 15.0)),
            "solar_thermal_area_m2": float(raw.get("solar_thermal_area_m2", 0.0) or 0.0),
            "solar_thermal_tilt_deg": float(raw.get("solar_thermal_tilt_deg", 18.0)),
            "solar_thermal_azimuth_deg": float(raw.get("solar_thermal_azimuth_deg", 0.0)),
        }
        if hwb_value > 0:
            spec["thermal"]["hwb_kwh_m2"] = hwb_value
        if "optimizer_flex" in raw:
            spec["optimizer_flex"] = bool(raw["optimizer_flex"])
        window = raw.get("thermal_flex_window")
        if isinstance(window, dict) and window:
            spec["thermal_flex_window"] = dict(window)
        if "max_on_quarterhours" in raw:
            spec["max_on_quarterhours"] = max(4, int(raw.get("max_on_quarterhours", 16) or 16))
        if "max_pulses_per_day" in raw:
            spec["max_pulses_per_day"] = max(1, int(raw.get("max_pulses_per_day", 4) or 4))
        _copy_loxone_binding(raw, spec)
    elif consumer_type == "thermal_rc":
        spec["thermal_rc"] = _normalize_thermal_rc(raw, index, profile_id)
        min_on = raw.get("min_on_quarterhours")
        if min_on is not None:
            spec["min_on_quarterhours"] = max(0, int(min_on) or 0)
        if raw.get("heating_power_threshold_kw") is not None:
            spec["heating_power_threshold_kw"] = float(raw["heating_power_threshold_kw"])
        if raw.get("actual_temp_step_c") is not None:
            spec["actual_temp_step_c"] = float(raw["actual_temp_step_c"])
        _copy_loxone_binding(raw, spec)
        thermal_control = raw.get("thermal_control")
        if isinstance(thermal_control, dict):
            loxone = thermal_control.get("loxone")
            if isinstance(loxone, dict) and loxone:
                spec["thermal_control"] = {"loxone": dict(loxone)}
    legacy_id = str(raw.get("legacy_id", "")).strip()
    if legacy_id and legacy_id != consumer_id:
        spec["legacy_id"] = legacy_id
    return spec


def _normalize_profile(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"profiles[{index}] muss ein Objekt sein.")
    profile_id = str(raw.get("id", "")).strip()
    if not profile_id:
        raise ValueError(f"profiles[{index}]: id fehlt.")
    label = str(raw.get("label", profile_id)).strip() or profile_id
    annual_kwh = float(raw.get("annual_kwh", 0.0) or 0.0)
    total_profile_csv = str(raw.get("total_profile_csv", "")).strip()
    consumers_raw = raw.get("consumers", [])
    if not isinstance(consumers_raw, list):
        raise ValueError(f"profiles '{profile_id}': consumers muss ein Array sein.")
    has_thermal = any(
        str(item.get("type", "")).strip().lower() == "thermal_annual"
        for item in consumers_raw
        if isinstance(item, dict)
    )
    if has_thermal and (raw.get("latitude") is None or raw.get("longitude") is None):
        raise ValueError(
            f"profiles '{profile_id}': latitude und longitude sind bei "
            "thermal_annual-Verbraucher erforderlich."
        )
    latitude = float(raw.get("latitude", 48.0) or 48.0)
    longitude = float(raw.get("longitude", 10.0) or 10.0)
    timezone_name = lookup_timezone_name(latitude, longitude)
    default_pv_tilt = float(raw.get("default_pv_tilt", 25.0) or 25.0)
    default_pv_azimuth = float(raw.get("default_pv_azimuth", 0.0) or 0.0)
    consumers: list[dict] = []
    seen: set[str] = set()
    thermal_consumer_indices: list[int] = []
    for c_index, item in enumerate(consumers_raw):
        consumer = _normalize_consumer(item, c_index, profile_id)
        if consumer["type"] == "thermal_annual":
            thermal_consumer_indices.append(c_index)
        if consumer["type"] == "thermal_annual" and consumer.get("thermal"):
            consumer["thermal"]["latitude"] = latitude
            consumer["thermal"]["longitude"] = longitude
            consumer["thermal"]["timezone_name"] = timezone_name
        if consumer["type"] == "thermal_rc" and consumer.get("thermal_rc"):
            consumer["thermal_rc"]["latitude"] = latitude
            consumer["thermal_rc"]["longitude"] = longitude
            consumer["thermal_rc"]["timezone_name"] = timezone_name
        if consumer["id"] in seen:
            raise ValueError(
                f"profiles '{profile_id}': doppelte consumer id '{consumer['id']}'."
            )
        seen.add(consumer["id"])
        consumers.append(consumer)
    if len(thermal_consumer_indices) > 1:
        raise ValueError(
            f"profiles '{profile_id}': nur ein Verbraucher vom Typ "
            "'thermal_annual' (Haus Wärme) erlaubt."
        )
    if thermal_consumer_indices and thermal_consumer_indices[0] != 0:
        raise ValueError(
            f"profiles '{profile_id}': Typ 'thermal_annual' (Haus Wärme) "
            "nur für Verbraucher 1 erlaubt."
        )
    baseload = compute_baseload_kwh(annual_kwh, consumers)
    return {
        "id": profile_id,
        "label": label,
        "annual_kwh": annual_kwh,
        "latitude": latitude,
        "longitude": longitude,
        "timezone_name": timezone_name,
        "default_pv_tilt": default_pv_tilt,
        "default_pv_azimuth": default_pv_azimuth,
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


def _serialize_profile(profile: dict) -> dict:
    out: dict = {
        "id": profile["id"],
        "label": profile["label"],
        "annual_kwh": profile["annual_kwh"],
        "total_profile_csv": profile.get("total_profile_csv", ""),
        "consumers": [_serialize_consumer(c) for c in profile["consumers"]],
    }
    if profile.get("latitude") is not None:
        out["latitude"] = profile["latitude"]
    if profile.get("longitude") is not None:
        out["longitude"] = profile["longitude"]
    if profile.get("timezone_name"):
        out["timezone_name"] = profile["timezone_name"]
    if profile.get("default_pv_tilt") is not None:
        out["default_pv_tilt"] = profile["default_pv_tilt"]
    if profile.get("default_pv_azimuth") is not None:
        out["default_pv_azimuth"] = profile["default_pv_azimuth"]
    return out


def save_house_profiles_document(path: str, doc: dict) -> None:
    normalized = normalize_house_profiles_document(doc)
    serializable = {
        "profiles": [_serialize_profile(p) for p in normalized["profiles"].values()]
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
    }
    if consumer.get("profile_csv"):
        out["profile_csv"] = consumer["profile_csv"]
    if consumer["type"] == "generic":
        out["annual_kwh"] = consumer.get("annual_kwh", 0.0)
        if consumer.get("schedule"):
            out["schedule"] = consumer["schedule"]
        if consumer.get("earnie_role"):
            out["earnie_role"] = consumer["earnie_role"]
        rec = consumer.get("appliance_recommendation")
        if isinstance(rec, dict):
            out["appliance_recommendation"] = dict(rec)
        if consumer.get("loxone_inputs"):
            out["loxone_inputs"] = dict(consumer["loxone_inputs"])
        if consumer.get("legacy_id"):
            out["legacy_id"] = consumer["legacy_id"]
    elif consumer["type"] == "ev":
        out["min_power_kw"] = consumer.get("min_power_kw", 0.0)
        out["min_on_quarterhours"] = consumer.get("min_on_quarterhours", 0)
        out["battery_capacity_kwh"] = consumer["battery_capacity_kwh"]
        out["charging_schedule"] = consumer["charging_schedule"]
        if consumer.get("loxone_inputs"):
            out["loxone_inputs"] = dict(consumer["loxone_inputs"])
        if consumer.get("loxone_outputs"):
            out["loxone_outputs"] = dict(consumer["loxone_outputs"])
        if consumer.get("legacy_id"):
            out["legacy_id"] = consumer["legacy_id"]
    if consumer["type"] == "thermal_annual" and consumer.get("thermal"):
        thermal = dict(consumer["thermal"])
        thermal.pop("latitude", None)
        thermal.pop("longitude", None)
        out.update(thermal)
        if consumer.get("loxone_inputs"):
            out["loxone_inputs"] = dict(consumer["loxone_inputs"])
        if consumer.get("loxone_outputs"):
            out["loxone_outputs"] = dict(consumer["loxone_outputs"])
        if consumer.get("legacy_id"):
            out["legacy_id"] = consumer["legacy_id"]
    elif consumer["type"] == "thermal_rc":
        rc = consumer.get("thermal_rc")
        if isinstance(rc, dict):
            out["thermal_rc"] = dict(rc)
        if consumer.get("min_on_quarterhours") is not None:
            out["min_on_quarterhours"] = consumer["min_on_quarterhours"]
        if consumer.get("heating_power_threshold_kw") is not None:
            out["heating_power_threshold_kw"] = consumer["heating_power_threshold_kw"]
        if consumer.get("actual_temp_step_c") is not None:
            out["actual_temp_step_c"] = consumer["actual_temp_step_c"]
        if consumer.get("loxone_inputs"):
            out["loxone_inputs"] = dict(consumer["loxone_inputs"])
        if consumer.get("loxone_outputs"):
            out["loxone_outputs"] = dict(consumer["loxone_outputs"])
        if consumer.get("thermal_control"):
            out["thermal_control"] = dict(consumer["thermal_control"])
        if consumer.get("legacy_id"):
            out["legacy_id"] = consumer["legacy_id"]
    return out


def profile_list(doc: dict) -> list[dict]:
    return list(doc.get("profiles", {}).values())


def load_profile_total_series(profile: dict) -> list[tuple[str, float]] | None:
    """Lädt Gesamtverbrauchs-CSV falls gesetzt."""
    csv_path = profile.get("total_profile_csv", "")
    if not csv_path:
        return None
    return load_hourly_profile_csv(csv_path)
