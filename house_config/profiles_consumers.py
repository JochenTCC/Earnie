"""Consumer entries of house profiles: normalize + serialize (split from profiles_store)."""
from __future__ import annotations

from house_config.earnie_role import (
    DEFAULT_MANUAL_HORIZON_H,
    EARNIE_ROLE_FLEX,
    EARNIE_ROLE_KNOWN,
    EARNIE_ROLES,
    infer_earnie_role_from_legacy,
)
from house_config.consumer_points_fields import (
    normalize_points_fields,
    serialize_points_fields,
)
from house_config.ev_profile import normalize_ev_charging_schedule
from house_config.generic_schedule import (
    derive_duration_h,
    generic_annual_kwh,
    normalize_generic_schedule,
)
from house_config.profiles_thermal_annual import normalize_thermal_annual_consumer
from settings.flexible_consumers import reject_legacy_id


CONSUMER_TYPES = frozenset({"generic", "thermal_annual", "ev", "thermal_rc"})


def _copy_loxone_binding(raw: dict, spec: dict) -> None:
    loxone_inputs = raw.get("loxone_inputs")
    if isinstance(loxone_inputs, dict) and loxone_inputs:
        spec["loxone_inputs"] = dict(loxone_inputs)
    loxone_outputs = raw.get("loxone_outputs")
    if isinstance(loxone_outputs, dict) and loxone_outputs:
        spec["loxone_outputs"] = dict(loxone_outputs)


def _clean_ehal_bindings(bindings: dict) -> dict[str, str]:
    """Keep activated binding keys; empty values are Loxone activation flags (Q8)."""
    cleaned: dict[str, str] = {}
    for key, value in bindings.items():
        field = str(key).strip()
        if not field:
            continue
        cleaned[field] = str(value).strip()
    return cleaned


def _copy_ehal_entity_fields(raw: dict, spec: dict) -> None:
    from ehal.flex_fields import expand_flex_bindings

    bindings = raw.get("ehal_bindings")
    if isinstance(bindings, dict) and bindings:
        cleaned = _clean_ehal_bindings(bindings)
        if cleaned:
            cid = str(spec.get("id") or raw.get("id") or "").strip()
            # expand_flex_bindings drops empty addresses — re-attach activation flags.
            expanded = expand_flex_bindings(cleaned, cid) if cid else dict(cleaned)
            for field, address in cleaned.items():
                if not address:
                    expanded.setdefault(field, "")
            spec["ehal_bindings"] = expanded


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


def _normalize_ev_consumer(raw: dict, spec: dict, *, profile_id: str, index: int) -> None:
    battery_capacity = float(raw.get("battery_capacity_kwh", 0.0) or 0.0)
    if battery_capacity <= 0:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}]: "
            "battery_capacity_kwh muss > 0 sein."
        )
    spec["min_power_kw"] = float(raw.get("min_power_kw", 0.0) or 0.0)
    if spec["min_power_kw"] < 0.0:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}] '{spec['id']}': "
            "min_power_kw muss >= 0 sein."
        )
    if spec["min_power_kw"] > spec["nominal_power_kw"] + 1e-9:
        raise ValueError(
            f"profiles '{profile_id}' consumers[{index}] '{spec['id']}': "
            f"min_power_kw ({spec['min_power_kw']}) darf nicht größer als "
            f"nominal_power_kw ({spec['nominal_power_kw']}) sein."
        )
    spec["min_on_quarterhours"] = max(0, int(raw.get("min_on_quarterhours", 4) or 4))
    spec["battery_capacity_kwh"] = battery_capacity
    spec["charging_schedule"] = normalize_ev_charging_schedule(raw.get("charging_schedule"))
    _copy_loxone_binding(raw, spec)


def _normalize_thermal_annual_consumer(raw: dict, spec: dict) -> None:
    normalize_thermal_annual_consumer(raw, spec, copy_loxone_binding=_copy_loxone_binding)


def _normalize_thermal_rc_consumer(
    raw: dict, spec: dict, *, profile_id: str, index: int
) -> None:
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


def _normalize_consumer(raw: dict, index: int, profile_id: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"profiles '{profile_id}' consumers[{index}] muss ein Objekt sein.")
    consumer_id = str(raw.get("id", "")).strip()
    if not consumer_id:
        raise ValueError(f"profiles '{profile_id}' consumers[{index}]: id fehlt.")
    reject_legacy_id(raw, f"{profile_id}/{consumer_id}")
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
        "use_profile_csv": bool(raw.get("use_profile_csv", False)),
        "absent_mode_enabled": bool(raw.get("absent_mode_enabled", False)),
    }
    if "id_locked" in raw:
        spec["id_locked"] = bool(raw.get("id_locked"))
    provisional = str(raw.get("id_provisional_label") or "").strip()
    if provisional and not spec.get("id_locked", True):
        spec["id_provisional_label"] = provisional
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
        _normalize_ev_consumer(raw, spec, profile_id=profile_id, index=index)
    if consumer_type == "thermal_annual":
        _normalize_thermal_annual_consumer(raw, spec)
    elif consumer_type == "thermal_rc":
        _normalize_thermal_rc_consumer(raw, spec, profile_id=profile_id, index=index)
    normalize_points_fields(raw, spec, profile_id=profile_id, index=index)
    _copy_ehal_entity_fields(raw, spec)
    return spec


def _attach_ehal_entity_fields(out: dict, consumer: dict) -> None:
    if consumer.get("ehal_bindings"):
        out["ehal_bindings"] = dict(consumer["ehal_bindings"])


def _copy_loxone_io_fields(consumer: dict, out: dict, *, outputs: bool = True) -> None:
    if consumer.get("loxone_inputs"):
        out["loxone_inputs"] = dict(consumer["loxone_inputs"])
    if outputs and consumer.get("loxone_outputs"):
        out["loxone_outputs"] = dict(consumer["loxone_outputs"])


def _serialize_generic_fields(consumer: dict, out: dict) -> None:
    out["annual_kwh"] = consumer.get("annual_kwh", 0.0)
    if consumer.get("schedule"):
        out["schedule"] = consumer["schedule"]
    if consumer.get("earnie_role"):
        out["earnie_role"] = consumer["earnie_role"]
    rec = consumer.get("appliance_recommendation")
    if isinstance(rec, dict):
        cleaned = dict(rec)
        cleaned.pop("default_runtime_h", None)
        out["appliance_recommendation"] = cleaned
    _copy_loxone_io_fields(consumer, out, outputs=False)


def _serialize_ev_fields(consumer: dict, out: dict) -> None:
    out["min_power_kw"] = consumer.get("min_power_kw", 0.0)
    out["min_on_quarterhours"] = consumer.get("min_on_quarterhours", 4)
    out["battery_capacity_kwh"] = consumer["battery_capacity_kwh"]
    out["charging_schedule"] = consumer["charging_schedule"]
    _copy_loxone_io_fields(consumer, out)


def _serialize_thermal_annual_fields(consumer: dict, out: dict) -> None:
    thermal = dict(consumer["thermal"])
    thermal.pop("latitude", None)
    thermal.pop("longitude", None)
    out.update(thermal)
    out["min_on_quarterhours"] = consumer.get("min_on_quarterhours", 4)
    _copy_loxone_io_fields(consumer, out)


def _serialize_thermal_rc_fields(consumer: dict, out: dict) -> None:
    rc = consumer.get("thermal_rc")
    if isinstance(rc, dict):
        out["thermal_rc"] = dict(rc)
    if consumer.get("min_on_quarterhours") is not None:
        out["min_on_quarterhours"] = consumer["min_on_quarterhours"]
    if consumer.get("heating_power_threshold_kw") is not None:
        out["heating_power_threshold_kw"] = consumer["heating_power_threshold_kw"]
    if consumer.get("actual_temp_step_c") is not None:
        out["actual_temp_step_c"] = consumer["actual_temp_step_c"]
    _copy_loxone_io_fields(consumer, out)
    if consumer.get("thermal_control"):
        out["thermal_control"] = dict(consumer["thermal_control"])


def _serialize_consumer(consumer: dict) -> dict:
    out: dict = {
        "id": consumer["id"],
        "label": consumer["label"],
        "type": consumer["type"],
        "nominal_power_kw": consumer["nominal_power_kw"],
    }
    if "id_locked" in consumer:
        out["id_locked"] = bool(consumer.get("id_locked"))
    provisional = str(consumer.get("id_provisional_label") or "").strip()
    if provisional and not out.get("id_locked", True):
        out["id_provisional_label"] = provisional
    if consumer.get("profile_csv"):
        out["profile_csv"] = consumer["profile_csv"]
    out["use_profile_csv"] = bool(consumer.get("use_profile_csv", False))
    out["absent_mode_enabled"] = bool(consumer.get("absent_mode_enabled", False))
    if consumer["type"] == "generic":
        _serialize_generic_fields(consumer, out)
    elif consumer["type"] == "ev":
        _serialize_ev_fields(consumer, out)
    if consumer["type"] == "thermal_annual" and consumer.get("thermal"):
        _serialize_thermal_annual_fields(consumer, out)
    elif consumer["type"] == "thermal_rc":
        _serialize_thermal_rc_fields(consumer, out)
    serialize_points_fields(consumer, out)
    _attach_ehal_entity_fields(out, consumer)
    return out
