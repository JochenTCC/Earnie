"""Normalize thermal_annual consumer fields for house profiles."""
from __future__ import annotations

from house_config.heat_source import reject_legacy_heat_pump_type
from house_config.heating_systems import (
    HEATING_SYSTEM_ID_KEY,
    apply_heating_system,
    reject_inline_heating_fields,
    reject_measured_rod_fields,
    resolve_heating_system,
)
from house_config.profile_schema_defaults import consumer_default


def absent_temp_reduction_c(raw: dict, target_temp_c: float) -> float:
    """Resolve Kelvin reduction; migrate legacy absolute ``absent_temp_c``."""
    if raw.get("absent_temp_reduction_c") not in (None, ""):
        return max(0.0, float(raw["absent_temp_reduction_c"]))
    if raw.get("absent_temp_c") not in (None, ""):
        return max(0.0, float(target_temp_c) - float(raw["absent_temp_c"]))
    return float(consumer_default("absent_temp_reduction_c"))


def int_or_default(value: object, default: int) -> int:
    """``int(value)``; only a missing / ``None`` / empty value yields ``default`` (0 is kept)."""
    if value is None or value == "":
        return default
    return int(value)


def _persons(raw: dict) -> int:
    persons = int_or_default(
        _raw_thermal_field(raw, "persons"), int(consumer_default("persons"))
    )
    if persons < 1:
        raise ValueError(
            f"thermal_annual: persons muss >= 1 sein (ist {persons}). "
            "Abwesenheit wird über den Abwesenheitsmodus abgebildet, nicht über 0 Personen."
        )
    return persons


def _raw_thermal_field(raw: dict, key: str):
    if raw.get(key) not in (None, ""):
        return raw.get(key)
    nested = raw.get("thermal")
    if isinstance(nested, dict) and nested.get(key) not in (None, ""):
        return nested.get(key)
    return None


def _label(raw: dict) -> str:
    return f"thermal_annual '{raw.get('id') or '?'}'"


def _build_thermal_block(raw: dict) -> dict:
    """Building part of ``spec['thermal']`` (defaults for missing fields).

    The heat generation (``heat_source``, ``heat_storage``) comes from the heating-system
    catalog, see ``apply_heating_system``.
    """
    from optimizer.thermal_house import normalize_building_mass

    reject_legacy_heat_pump_type(raw, label=_label(raw))
    hwb_raw = _raw_thermal_field(raw, "hwb_kwh_m2")
    hwb_value = float(hwb_raw) if hwb_raw not in (None, "") else 0.0
    target_temp_c = float(
        _raw_thermal_field(raw, "target_temp_c") or consumer_default("target_temp_c")
    )
    mass = normalize_building_mass(
        _raw_thermal_field(raw, "building_mass") or consumer_default("building_mass")
    )
    tol_raw = _raw_thermal_field(raw, "house_tolerance_c")
    house_tol = (
        max(0.05, float(tol_raw))
        if tol_raw not in (None, "")
        else float(consumer_default("house_tolerance_c"))
    )
    area_raw = _raw_thermal_field(raw, "living_area_m2")
    thermal = {
        "living_area_m2": float(
            consumer_default("living_area_m2") if area_raw is None else area_raw
        ),
        "building_class": int(
            _raw_thermal_field(raw, "building_class")
            or consumer_default("building_class")
        ),
        "persons": _persons(raw),
        "target_temp_c": target_temp_c,
        "absent_temp_reduction_c": absent_temp_reduction_c(raw, target_temp_c),
        "heating_limit_c": float(
            _raw_thermal_field(raw, "heating_limit_c")
            or consumer_default("heating_limit_c")
        ),
        "solar_thermal_area_m2": float(
            _raw_thermal_field(raw, "solar_thermal_area_m2")
            or consumer_default("solar_thermal_area_m2")
        ),
        "solar_thermal_tilt_deg": float(
            consumer_default("solar_thermal_tilt_deg")
            if _raw_thermal_field(raw, "solar_thermal_tilt_deg") is None
            else _raw_thermal_field(raw, "solar_thermal_tilt_deg")
        ),
        "solar_thermal_azimuth_deg": float(
            _raw_thermal_field(raw, "solar_thermal_azimuth_deg")
            or consumer_default("solar_thermal_azimuth_deg")
        ),
        "building_mass": mass,
        "house_tolerance_c": house_tol,
    }
    if hwb_value > 0:
        thermal["hwb_kwh_m2"] = hwb_value
    h_override = _raw_thermal_field(raw, "house_heat_loss_kw_per_k")
    if h_override not in (None, "") and float(h_override) > 0.0:
        thermal["house_heat_loss_kw_per_k"] = float(h_override)
    return thermal


def normalize_thermal_annual_consumer(
    raw: dict,
    spec: dict,
    *,
    copy_loxone_binding,
    heating_systems: dict | None,
) -> None:
    """Fill ``spec['thermal']`` and related flex fields for thermal_annual.

    The reference heating system (``heating_system_id``) is resolved against the catalog and
    placed into the spec; inline generation fields and measured-rod fields fail loud.
    """
    reject_inline_heating_fields(raw, label=_label(raw))
    reject_measured_rod_fields(raw, label=_label(raw))
    system = resolve_heating_system(
        heating_systems, raw.get(HEATING_SYSTEM_ID_KEY), label=_label(raw)
    )
    spec[HEATING_SYSTEM_ID_KEY] = system["id"]
    spec["thermal"] = _build_thermal_block(raw)
    apply_heating_system(spec, system)
    if "optimizer_flex" in raw:
        spec["optimizer_flex"] = bool(raw["optimizer_flex"])
    window = raw.get("thermal_flex_window")
    if isinstance(window, dict) and window:
        spec["thermal_flex_window"] = dict(window)
    if "max_on_quarterhours" in raw:
        spec["max_on_quarterhours"] = max(4, int(raw.get("max_on_quarterhours", 16) or 16))
    if "max_pulses_per_day" in raw:
        spec["max_pulses_per_day"] = max(1, int(raw.get("max_pulses_per_day", 4) or 4))
    copy_loxone_binding(raw, spec)
