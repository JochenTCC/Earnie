"""Thermal properties of the building at house-profile level.

The building's thermal properties belong to the house, not to its heating consumer::

    {"id": "haus", ..., "heating_enabled": true, "persons": 2,
     "thermal": {"living_area_m2": 140.0, "building_class": 3, "building_mass": "mittel",
                 "target_temp_c": 21.5, "heating_limit_c": 15.0, "house_tolerance_c": 0.5,
                 "absent_mode_enabled": false, "absent_temp_reduction_c": 2.5},
     "consumers": [{"type": "thermal_annual", "heating_system_id": "heating_haus", ...}]}

``heating_enabled`` is the switch „Heizung betrachten“. Off: the ``thermal_annual`` consumer is
not planned (the normalized profile keeps it under ``inactive_consumers``, so a save writes it
back unchanged) and its consumption stays in the baseload; the ``thermal`` block is kept too.
The loader places the house block (plus ``persons``) into the normalized consumer's ``thermal``,
so the calculation core reads the same fields as before.
"""
from __future__ import annotations

from typing import Any

from house_config.profile_schema_defaults import house_thermal_default, profile_default

HEATING_ENABLED_KEY = "heating_enabled"
HOUSE_THERMAL_KEY = "thermal"
PERSONS_KEY = "persons"
# Normalized profile only: thermal_annual consumers of a house with the switch off.
INACTIVE_CONSUMERS_KEY = "inactive_consumers"

# Building fields of the house block (``house_heat_loss_kw_per_k`` and ``hwb_kwh_m2`` optional).
HOUSE_THERMAL_FIELDS: tuple[str, ...] = (
    "living_area_m2",
    "hwb_kwh_m2",
    "building_class",
    "building_mass",
    "target_temp_c",
    "heating_limit_c",
    "house_tolerance_c",
    "house_heat_loss_kw_per_k",
    "absent_mode_enabled",
    "absent_temp_reduction_c",
)
# Fields a thermal_annual consumer carried before they moved to the house (dm5.house_thermal).
# ``absent_mode_enabled`` is a generic consumer field and stays out of this list.
CONSUMER_BUILDING_FIELDS: tuple[str, ...] = (
    "living_area_m2",
    "hwb_kwh_m2",
    "building_class",
    "building_mass",
    "target_temp_c",
    "heating_limit_c",
    "house_tolerance_c",
    "house_heat_loss_kw_per_k",
    "absent_temp_reduction_c",
    "absent_temp_c",
    "persons",
)
_MIGRATE_HINT = (
    "Konfiguration migrieren (Streamlit-Seite „Konfigurations-Migration“ oder "
    "python -m scripts.migrate_config --config-dir <config>)"
)


def normalize_persons(raw: Any, *, label: str) -> int:
    """House-level ``persons`` (missing = schema default)."""
    if raw is None or raw == "":
        return int(profile_default(PERSONS_KEY))
    persons = int(raw)
    if persons < 1:
        raise ValueError(
            f"{label}: persons muss >= 1 sein (ist {persons}). Abwesenheit wird über den "
            "Abwesenheitsmodus abgebildet, nicht über 0 Personen."
        )
    return persons


def _number(block: dict, key: str) -> float:
    value = block.get(key)
    return float(house_thermal_default(key) if value in (None, "") else value)


def normalize_house_thermal(raw: Any, *, label: str) -> dict[str, Any]:
    """Validated house ``thermal`` block (documented schema defaults for missing fields)."""
    from optimizer.thermal_house import normalize_building_mass

    if not isinstance(raw, dict):
        raise ValueError(f"{label}: thermal muss ein Objekt sein.")
    extra = sorted(set(raw) - set(HOUSE_THERMAL_FIELDS))
    if extra:
        raise ValueError(f"{label}: thermal enthält unbekannte Felder {', '.join(extra)}.")
    building_class_raw = raw.get("building_class")
    building_class = int(
        house_thermal_default("building_class")
        if building_class_raw in (None, "")
        else building_class_raw
    )
    if building_class not in (1, 2, 3, 4):
        raise ValueError(
            f"{label}: thermal.building_class muss 1 bis 4 sein (ist {building_class})."
        )
    tolerance = _number(raw, "house_tolerance_c")
    if tolerance < 0.05:
        raise ValueError(
            f"{label}: thermal.house_tolerance_c muss >= 0.05 sein (ist {tolerance})."
        )
    reduction = _number(raw, "absent_temp_reduction_c")
    if reduction < 0.0:
        raise ValueError(
            f"{label}: thermal.absent_temp_reduction_c muss >= 0 sein (ist {reduction})."
        )
    out: dict[str, Any] = {
        "living_area_m2": _number(raw, "living_area_m2"),
        "building_class": building_class,
        "building_mass": normalize_building_mass(
            raw.get("building_mass") or house_thermal_default("building_mass")
        ),
        "target_temp_c": _number(raw, "target_temp_c"),
        "heating_limit_c": _number(raw, "heating_limit_c"),
        "house_tolerance_c": tolerance,
        "absent_mode_enabled": bool(
            raw.get("absent_mode_enabled", house_thermal_default("absent_mode_enabled"))
        ),
        "absent_temp_reduction_c": reduction,
    }
    hwb = raw.get("hwb_kwh_m2")
    if hwb not in (None, "") and float(hwb) > 0.0:
        out["hwb_kwh_m2"] = float(hwb)
    h_override = raw.get("house_heat_loss_kw_per_k")
    if h_override not in (None, "") and float(h_override) > 0.0:
        out["house_heat_loss_kw_per_k"] = float(h_override)
    return out


def default_house_thermal() -> dict[str, Any]:
    """House block with every documented default (form seed of a house without one)."""
    return normalize_house_thermal({}, label="Hausprofil")


def serialize_house_thermal(block: dict[str, Any]) -> dict[str, Any]:
    return {key: block[key] for key in HOUSE_THERMAL_FIELDS if key in block}


def heating_enabled(raw_profile: dict, *, label: str, has_thermal_consumer: bool) -> bool:
    """The switch „Heizung betrachten“ of a raw profile.

    Missing means off (the documented default of a new house) as long as the house has no
    ``thermal_annual`` consumer; a heating consumer without the switch is the file shape
    before ``dm5.house_thermal`` and fails loud.
    """
    value = raw_profile.get(HEATING_ENABLED_KEY)
    if value is None:
        if has_thermal_consumer:
            raise ValueError(
                f"{label}: heating_enabled fehlt (Gebäude-Wärmedaten gehören ans Hausprofil) "
                f"— {_MIGRATE_HINT}."
            )
        return False
    if not isinstance(value, bool):
        raise ValueError(f"{label}: heating_enabled muss true oder false sein.")
    return value


def reject_consumer_building_fields(raw: dict, *, label: str) -> None:
    """Building fields on a raw ``thermal_annual`` consumer fail loud (they live at the house).

    Only flat keys count: a normalized consumer handed back for saving carries them nested in
    ``thermal`` (filled from the house), which the loader ignores.
    """
    present = [key for key in CONSUMER_BUILDING_FIELDS if key in raw]
    if present:
        raise ValueError(
            f"{label}: {', '.join(present)} gehört ans Hausprofil (Abschnitt „Gebäude / "
            f"Wärmebedarf“, Schlüssel thermal bzw. persons), nicht an den Verbraucher — "
            f"{_MIGRATE_HINT}."
        )


def consumer_thermal_from_house(house_thermal: dict[str, Any], persons: int) -> dict[str, Any]:
    """Building part of a normalized consumer's ``thermal`` (without absent-mode switch)."""
    out = {k: v for k, v in house_thermal.items() if k != "absent_mode_enabled"}
    out[PERSONS_KEY] = persons
    return out


def drop_house_fields(consumer: dict[str, Any]) -> dict[str, Any]:
    """Consumer copy without the building fields (house-configurator save)."""
    return {k: v for k, v in consumer.items() if k not in CONSUMER_BUILDING_FIELDS}
