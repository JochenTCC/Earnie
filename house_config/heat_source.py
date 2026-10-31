"""Heat source of a thermal_annual consumer and its heating rod part (SUSI P1).

Stored shape on the consumer (flat, next to ``heat_storage``)::

    "heat_source": {"type": "heat_pump", "heat_pump_type": "erde",
                    "efficiency": 4.3, "fuel_price": 10.43},
    "parts": [{"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}]

``efficiency`` and ``fuel_price`` are optional; missing values come from
``share/config/heat_source_defaults.json`` (documented source per value). Efficiency is
the seasonal performance factor (JAZ) for heat pumps and the annual efficiency
(Nutzungsgrad) for every other type. ``fuel_price`` is in the carrier's own unit
(``fuel_unit``). The heating rod charges the heat storage with η = 1, so it exists only
together with ``heat_storage`` (data-model decision D1: a part, not a sibling consumer).
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

HEAT_SOURCE_TYPES: tuple[str, ...] = (
    "heat_pump",
    "oil",
    "gas",
    "pellets",
    "district_heat",
    "wood",
    "electric_direct",
)
HEAT_PUMP_TYPES: tuple[str, ...] = ("luft", "erde", "grundwasser")
HEATING_ROD_PART_ID = "heating_rod"
HEATING_ROD_PART_TYPE = "heating_rod"
PART_TYPES: tuple[str, ...] = (HEATING_ROD_PART_TYPE,)
LEGACY_HEAT_PUMP_TYPE_KEY = "heat_pump_type"

_DEFAULTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "share",
    "config",
    "heat_source_defaults.json",
)
_MIGRATE_HINT = (
    "Konfiguration migrieren (Streamlit-Seite „Konfigurations-Migration“ oder "
    "python -m scripts.migrate_config --config-dir <config>)"
)


@lru_cache(maxsize=1)
def heat_source_defaults() -> dict[str, Any]:
    with open(_DEFAULTS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _type_defaults(source_type: str) -> dict[str, Any]:
    return heat_source_defaults()["types"][source_type]


def part_kennung(consumer_id: str, part_id: str) -> str:
    """Composite wire Kennung of a part (D1); the relation is never parsed back."""
    return f"{consumer_id}_{part_id}"


def _positive(value: Any, label: str) -> float:
    number = float(value)
    if number <= 0.0:
        raise ValueError(f"{label} muss > 0 sein (ist {number}).")
    return number


def normalize_heat_source(raw: Any, *, label: str) -> dict[str, Any]:
    """Validated ``heat_source`` (fail loud on unknown keys); only stored fields are kept.

    Defaults are resolved by the getters below, so a normalized profile saved back to disk
    never gains default values.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{label}: heat_source fehlt (Objekt mit type) — {_MIGRATE_HINT}.")
    source_type = str(raw.get("type") or "").strip().lower()
    if source_type not in HEAT_SOURCE_TYPES:
        raise ValueError(
            f"{label}: heat_source.type '{source_type}' unbekannt "
            f"(erlaubt: {', '.join(HEAT_SOURCE_TYPES)})."
        )
    allowed = {"type", "efficiency"}
    out: dict[str, Any] = {"type": source_type}
    if source_type == "heat_pump":
        allowed.add("heat_pump_type")
        hp_type = str(raw.get("heat_pump_type") or "").strip().lower()
        if hp_type not in HEAT_PUMP_TYPES:
            raise ValueError(
                f"{label}: heat_source.heat_pump_type '{hp_type}' unbekannt "
                f"(erlaubt: {', '.join(HEAT_PUMP_TYPES)})."
            )
        out["heat_pump_type"] = hp_type
    if not _type_defaults(source_type)["electric"]:
        allowed.add("fuel_price")
        price = raw.get("fuel_price")
        if price not in (None, ""):
            out["fuel_price"] = _positive(price, f"{label}: heat_source.fuel_price")
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ValueError(
            f"{label}: heat_source enthält unbekannte Felder für type '{source_type}': "
            f"{', '.join(extra)}."
        )
    eff = raw.get("efficiency")
    if eff not in (None, ""):
        out["efficiency"] = _positive(eff, f"{label}: heat_source.efficiency")
    return out


def heat_source_is_electric(heat_source: dict[str, Any]) -> bool:
    return bool(_type_defaults(str(heat_source["type"]))["electric"])


def heat_source_efficiency(heat_source: dict[str, Any]) -> float:
    """JAZ (heat pump) or Nutzungsgrad; profile value, else the documented default."""
    if heat_source.get("efficiency") is not None:
        return float(heat_source["efficiency"])
    return default_efficiency(heat_source)


def default_efficiency(heat_source: dict[str, Any]) -> float:
    source_type = str(heat_source["type"])
    if source_type == "heat_pump":
        hp_type = str(heat_source["heat_pump_type"])
        return float(heat_source_defaults()["heat_pump_types"][hp_type]["efficiency"])
    return float(_type_defaults(source_type)["efficiency"])


def fuel_unit(heat_source: dict[str, Any]) -> str | None:
    if heat_source_is_electric(heat_source):
        return None
    return str(_type_defaults(str(heat_source["type"]))["fuel_unit"])


def fuel_price_in_unit(heat_source: dict[str, Any]) -> float | None:
    """Fuel price in ``fuel_unit`` (profile value, else the documented default)."""
    if heat_source_is_electric(heat_source):
        return None
    if heat_source.get("fuel_price") is not None:
        return float(heat_source["fuel_price"])
    return float(_type_defaults(str(heat_source["type"]))["fuel_price"])


def fuel_price_eur_per_kwh(heat_source: dict[str, Any]) -> float | None:
    """€ per kWh of fuel (final energy), from the unit price and the energy content."""
    price = fuel_price_in_unit(heat_source)
    if price is None:
        return None
    defaults = _type_defaults(str(heat_source["type"]))
    unit = str(defaults["fuel_unit"])
    kwh_per_unit = float(defaults["kwh_per_unit"])
    eur_per_unit = price / 100.0 if unit.startswith("ct_") else price
    return eur_per_unit / kwh_per_unit


def fuel_co2_g_per_kwh(heat_source: dict[str, Any]) -> float | None:
    if heat_source_is_electric(heat_source):
        return None
    return float(_type_defaults(str(heat_source["type"]))["co2_g_per_kwh"])


def electricity_co2_g_per_kwh() -> float:
    return float(heat_source_defaults()["electricity_co2_g_per_kwh"])


def normalize_parts(
    raw_parts: Any,
    *,
    label: str,
    has_heat_storage: bool,
) -> list[dict[str, Any]]:
    """Validated ``parts[]`` of a thermal_annual consumer (only ``heating_rod`` in 2.8)."""
    if raw_parts in (None, []):
        return []
    if not isinstance(raw_parts, list):
        raise ValueError(f"{label}: parts muss eine Liste sein.")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, part in enumerate(raw_parts):
        where = f"{label}: parts[{index}]"
        if not isinstance(part, dict):
            raise ValueError(f"{where} muss ein Objekt sein.")
        part_id = str(part.get("id") or "").strip()
        part_type = str(part.get("type") or "").strip().lower()
        if part_type not in PART_TYPES:
            raise ValueError(
                f"{where}: type '{part_type}' unbekannt (erlaubt: {', '.join(PART_TYPES)})."
            )
        if part_id != HEATING_ROD_PART_ID:
            raise ValueError(f"{where}: id muss '{HEATING_ROD_PART_ID}' sein (ist '{part_id}').")
        if part_id in seen:
            raise ValueError(f"{where}: id '{part_id}' doppelt.")
        seen.add(part_id)
        extra = sorted(set(part) - {"id", "type", "nominal_power_kw"})
        if extra:
            raise ValueError(f"{where}: unbekannte Felder {', '.join(extra)}.")
        if not has_heat_storage:
            raise ValueError(
                f"{where}: Heizstab nur mit Wärmespeicher (heat_storage). Ohne Speicher "
                "die Hauptquelle „electric_direct“ (Stromheizung) wählen."
            )
        out.append(
            {
                "id": part_id,
                "type": part_type,
                "nominal_power_kw": _positive(
                    part.get("nominal_power_kw"), f"{where}.nominal_power_kw"
                ),
            }
        )
    return out


def heating_rod_part(consumer: dict[str, Any]) -> dict[str, Any] | None:
    for part in consumer.get("parts") or []:
        if part.get("type") == HEATING_ROD_PART_TYPE:
            return part
    return None


def reject_legacy_heat_pump_type(raw: dict[str, Any], *, label: str) -> None:
    nested = raw.get("thermal") if isinstance(raw.get("thermal"), dict) else {}
    if LEGACY_HEAT_PUMP_TYPE_KEY in raw or LEGACY_HEAT_PUMP_TYPE_KEY in nested:
        raise ValueError(
            f"{label}: heat_pump_type wird nicht mehr unterstützt (ersetzt durch "
            f"heat_source) — {_MIGRATE_HINT}."
        )


def consumer_heat_source(consumer: dict[str, Any]) -> dict[str, Any]:
    """``heat_source`` of a thermal_annual consumer (normalized ``thermal`` block or raw)."""
    thermal = consumer.get("thermal")
    raw = thermal.get("heat_source") if isinstance(thermal, dict) else None
    if raw is None:
        raw = consumer.get("heat_source")
    return normalize_heat_source(raw, label=f"thermal_annual '{consumer.get('id') or '?'}'")


def heating_rod_fuel_credit_cent_per_kwh(heat_source: dict[str, Any]) -> float | None:
    """Fuel cost a heating-rod kWh avoids (η_rod = 1): fuel €/kWh / efficiency, in cent."""
    eur = fuel_price_eur_per_kwh(heat_source)
    if eur is None:
        return None
    return eur / heat_source_efficiency(heat_source) * 100.0
