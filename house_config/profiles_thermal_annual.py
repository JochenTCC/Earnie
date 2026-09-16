"""Normalize thermal_annual consumer fields for house profiles."""
from __future__ import annotations


def absent_temp_reduction_c(raw: dict, target_temp_c: float) -> float:
    """Resolve Kelvin reduction; migrate legacy absolute ``absent_temp_c``."""
    if raw.get("absent_temp_reduction_c") not in (None, ""):
        return max(0.0, float(raw["absent_temp_reduction_c"]))
    if raw.get("absent_temp_c") not in (None, ""):
        return max(0.0, float(target_temp_c) - float(raw["absent_temp_c"]))
    return 6.5


def normalize_thermal_annual_consumer(
    raw: dict,
    spec: dict,
    *,
    copy_loxone_binding,
) -> None:
    """Fill ``spec['thermal']`` and related flex fields for thermal_annual."""
    hwb_raw = raw.get("hwb_kwh_m2")
    hwb_value = float(hwb_raw) if hwb_raw not in (None, "") else 0.0
    target_temp_c = float(raw.get("target_temp_c", 21.5))
    spec["thermal"] = {
        "living_area_m2": float(raw.get("living_area_m2", 0.0) or 0.0),
        "building_class": int(raw.get("building_class", 3)),
        "heat_pump_type": str(raw.get("heat_pump_type", "luft")).strip().lower(),
        "persons": int(raw.get("persons", 2)),
        "target_temp_c": target_temp_c,
        "absent_temp_reduction_c": absent_temp_reduction_c(raw, target_temp_c),
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
    spec["min_on_quarterhours"] = max(0, int(raw.get("min_on_quarterhours", 4) or 4))
    if "max_on_quarterhours" in raw:
        spec["max_on_quarterhours"] = max(4, int(raw.get("max_on_quarterhours", 16) or 16))
    if "max_pulses_per_day" in raw:
        spec["max_pulses_per_day"] = max(1, int(raw.get("max_pulses_per_day", 4) or 4))
    copy_loxone_binding(raw, spec)
