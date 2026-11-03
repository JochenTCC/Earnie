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
from house_config.house_thermal import (
    consumer_thermal_from_house,
    reject_consumer_building_fields,
)
from house_config.profile_schema_defaults import consumer_default


def int_or_default(value: object, default: int) -> int:
    """``int(value)``; only a missing / ``None`` / empty value yields ``default`` (0 is kept)."""
    if value is None or value == "":
        return default
    return int(value)


def _raw_thermal_field(raw: dict, key: str):
    if raw.get(key) not in (None, ""):
        return raw.get(key)
    nested = raw.get("thermal")
    if isinstance(nested, dict) and nested.get(key) not in (None, ""):
        return nested.get(key)
    return None


def _label(raw: dict) -> str:
    return f"thermal_annual '{raw.get('id') or '?'}'"


def _solar_thermal_fields(raw: dict) -> dict:
    """Solar-thermal collector of the consumer (heat generation, not the building)."""
    tilt = _raw_thermal_field(raw, "solar_thermal_tilt_deg")
    return {
        "solar_thermal_area_m2": float(
            _raw_thermal_field(raw, "solar_thermal_area_m2")
            or consumer_default("solar_thermal_area_m2")
        ),
        "solar_thermal_tilt_deg": float(
            consumer_default("solar_thermal_tilt_deg") if tilt is None else tilt
        ),
        "solar_thermal_azimuth_deg": float(
            _raw_thermal_field(raw, "solar_thermal_azimuth_deg")
            or consumer_default("solar_thermal_azimuth_deg")
        ),
    }


def _build_thermal_block(raw: dict, house_thermal: dict, persons: int) -> dict:
    """``spec['thermal']``: the house's building block plus the consumer's collector.

    The heat generation (``heat_source``, ``heat_storage``) comes from the heating-system
    catalog, see ``apply_heating_system``.
    """
    reject_legacy_heat_pump_type(raw, label=_label(raw))
    return {
        **consumer_thermal_from_house(house_thermal, persons),
        **_solar_thermal_fields(raw),
    }


def normalize_thermal_annual_consumer(
    raw: dict,
    spec: dict,
    *,
    copy_loxone_binding,
    heating_systems: dict | None,
    house_thermal: dict | None,
    persons: int,
) -> None:
    """Fill ``spec['thermal']`` and related flex fields for thermal_annual.

    The building fields come from the house profile (``house_thermal``, see
    ``house_config.house_thermal``); building fields on the consumer fail loud. The reference
    heating system (``heating_system_id``) is resolved against the catalog and placed into the
    spec; inline generation fields and measured-rod fields fail loud.
    """
    reject_consumer_building_fields(raw, label=_label(raw))
    if house_thermal is None:
        raise ValueError(
            f"{_label(raw)}: Hausprofil ohne Gebäude-Wärmedaten (thermal). Im "
            "Hauskonfigurator „Heizung betrachten“ einschalten und den Abschnitt „Gebäude / "
            "Wärmebedarf“ ausfüllen."
        )
    reject_inline_heating_fields(raw, label=_label(raw))
    reject_measured_rod_fields(raw, label=_label(raw))
    system = resolve_heating_system(
        heating_systems, raw.get(HEATING_SYSTEM_ID_KEY), label=_label(raw)
    )
    spec[HEATING_SYSTEM_ID_KEY] = system["id"]
    spec["thermal"] = _build_thermal_block(raw, house_thermal, persons)
    # The absent-mode setback is a house property; the core reads it on the consumer.
    spec["absent_mode_enabled"] = bool(house_thermal["absent_mode_enabled"])
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
